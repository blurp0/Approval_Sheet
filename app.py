import os
import sys
import subprocess
import sqlite3
import time
from datetime import datetime
from flask import Flask, redirect, render_template, request, send_file, flash, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "SEKRET-LANG-TO"

DB_FILE = "pdfs.db"
UPLOAD_FOLDER = "uploads"
PDF_FOLDER = "pdfs"
ALLOWED_EXTENSIONS = {".md", ".docx", ".html", ".txt"}
PDF_OPTIONS = ["--pdf-engine=xelatex", "--toc", "--highlight-style=pygments"]

# Ensure folders exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PDF_FOLDER"] = PDF_FOLDER


def allowed_file(filename):
    return any(filename.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS)


def query_pdfs(search_term=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if search_term:
        like = f"%{search_term}%"
        c.execute(
            """
            SELECT id, source_file, pdf_file, repo_name, commit_hash, created_at
            FROM pdf_files
            WHERE source_file LIKE ? OR pdf_file LIKE ? OR repo_name LIKE ?
            ORDER BY created_at DESC
            """,
            (like, like, like),
        )
    else:
        c.execute("SELECT id, source_file, pdf_file, repo_name, commit_hash, created_at FROM pdf_files ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows


def convert_to_pdf(source_path, pdf_path):
    subprocess.run(["pandoc", source_path, "-o", pdf_path] + PDF_OPTIONS, check=True)


def save_metadata(source_file, pdf_file, repo_name, commit_hash):
    created_at = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO pdf_files (source_file, pdf_file, repo_name, commit_hash, created_at) VALUES (?, ?, ?, ?, ?)",
        (source_file, pdf_file, repo_name, commit_hash, created_at),
    )
    conn.commit()
    conn.close()


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        uploaded = request.files.get("file")
        if not uploaded:
            flash("No file part", "warning")
            return redirect(request.url)

        if uploaded.filename == "":
            flash("No selected file", "warning")
            return redirect(request.url)

        if not allowed_file(uploaded.filename):
            flash("File type not allowed", "danger")
            return redirect(request.url)

        filename = secure_filename(uploaded.filename)
        source_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        # Handle duplicate filenames by appending timestamp
        if os.path.exists(source_path):
            base, ext = os.path.splitext(filename)
            filename = f"{base}_{int(time.time())}{ext}"
            source_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        uploaded.save(source_path)

        pdf_filename = os.path.splitext(filename)[0] + ".pdf"
        pdf_path = os.path.join(app.config["PDF_FOLDER"], pdf_filename)

        try:
            convert_to_pdf(source_path, pdf_path)
        except subprocess.CalledProcessError:
            flash("PDF conversion failed", "danger")
            return redirect(request.url)

        # For web uploads, we hardcode repo/commit info or you can extend with form inputs
        repo_name = "local-upload"
        commit_hash = "manual"

        try:
            save_metadata(filename, pdf_filename, repo_name, commit_hash)
        except Exception as e:
            flash(f"Database error: {e}", "danger")
            return redirect(request.url)

        flash(f"File '{filename}' uploaded and converted successfully!", "success")
        return redirect(url_for("index"))

    # GET request
    search = request.args.get("search")
    pdfs = query_pdfs(search)
    return render_template("index.html", pdfs=pdfs, search=search or "")


@app.route("/download/<filename>")
def download_file(filename):
    file_path = os.path.join(app.config["PDF_FOLDER"], filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    return "File not found", 404


def git_commit_push(commit_message):
    """
    Commit and push changes to the GitHub repo using the GITHUB_TOKEN for authentication.
    """
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")

    if not token or not repo:
        print("GITHUB_TOKEN or GITHUB_REPOSITORY not set in environment, cannot push.")
        return

    # Set remote URL with token auth
    remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"

    # Set remote origin with auth URL (overwrite existing origin)
    subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True)

    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", commit_message], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)


def batch_convert_and_push():
    """
    Batch convert all .md files in repo root (or subdirs),
    save PDFs to PDF_FOLDER,
    commit and push changes to repo.
    """
    repo_name = os.getenv("GITHUB_REPOSITORY", "local-repo")
    # We'll use current commit hash from git
    commit_hash = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        .stdout.strip()
    )

    converted_files = 0

    for root, dirs, files in os.walk("."):
        # Skip .git and PDF/UPLOAD folders
        if ".git" in dirs:
            dirs.remove(".git")
        if PDF_FOLDER in dirs:
            dirs.remove(PDF_FOLDER)
        if UPLOAD_FOLDER in dirs:
            dirs.remove(UPLOAD_FOLDER)

        for f in files:
            if f.lower().endswith(".md"):
                source_path = os.path.join(root, f)
                rel_source = os.path.relpath(source_path, ".")
                pdf_filename = os.path.splitext(f)[0] + ".pdf"
                pdf_path = os.path.join(PDF_FOLDER, pdf_filename)

                try:
                    convert_to_pdf(source_path, pdf_path)
                    save_metadata(rel_source, pdf_filename, repo_name, commit_hash)
                    print(f"Converted {rel_source} -> {pdf_filename}")
                    converted_files += 1
                except Exception as e:
                    print(f"Failed to convert {rel_source}: {e}")

    if converted_files > 0:
        commit_message = f"Auto convert {converted_files} markdown files to PDF"
        print(f"Committing and pushing: {commit_message}")
        git_commit_push(commit_message)
    else:
        print("No markdown files converted; skipping commit.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "batch":
        print("Running batch conversion mode...")
        batch_convert_and_push()
    else:
        app.run(debug=True)
