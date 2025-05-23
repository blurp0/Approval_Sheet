import os
import sys
import sqlite3
import time
import tempfile
from datetime import datetime
from flask import Flask, redirect, render_template, request, send_file, flash, url_for
from werkzeug.utils import secure_filename
from init_db import init_db
from docx2pdf import convert as docx2pdf_convert
import subprocess

init_db()

app = Flask(__name__)
app.secret_key = "SEKRET-LANG-TO"

DB_FILE = "pdfs.db"
PDF_FOLDER = "pdfs"
ALLOWED_EXTENSIONS = {".pdf", ".docx"}

os.makedirs(PDF_FOLDER, exist_ok=True)

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
        c.execute(
            "SELECT id, source_file, pdf_file, repo_name, commit_hash, created_at FROM pdf_files ORDER BY created_at DESC"
        )
    rows = c.fetchall()
    conn.close()
    return rows


def convert_docx_to_pdf(docx_path, pdf_path):
    # docx2pdf converts in-place, so convert docx_path folder then move PDF out
    temp_dir = os.path.dirname(docx_path)
    docx2pdf_convert(docx_path)  # This creates PDF next to docx_path
    expected_pdf = os.path.splitext(docx_path)[0] + ".pdf"
    if not os.path.exists(expected_pdf):
        raise FileNotFoundError(f"Expected PDF not found after conversion: {expected_pdf}")
    os.rename(expected_pdf, pdf_path)


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
        if not uploaded or uploaded.filename == "":
            flash("No file selected", "warning")
            return redirect(request.url)

        if not allowed_file(uploaded.filename):
            flash("File type not allowed. Only PDF and DOCX are supported.", "danger")
            return redirect(request.url)

        filename = secure_filename(uploaded.filename)
        ext = os.path.splitext(filename)[1].lower()
        pdf_filename = os.path.splitext(filename)[0] + ".pdf"
        pdf_path = os.path.join(app.config["PDF_FOLDER"], pdf_filename)

        try:
            if ext == ".pdf":
                # Save PDF directly
                uploaded.save(pdf_path)

            elif ext == ".docx":
                # Convert DOCX to PDF without saving DOCX permanently
                with tempfile.TemporaryDirectory() as tmpdir:
                    temp_docx_path = os.path.join(tmpdir, filename)
                    uploaded.save(temp_docx_path)
                    convert_docx_to_pdf(temp_docx_path, pdf_path)

        except Exception as e:
            flash(f"PDF conversion failed: {e}", "danger")
            return redirect(request.url)

        repo_name = "local-upload"
        commit_hash = "manual"

        try:
            save_metadata(filename, pdf_filename, repo_name, commit_hash)
        except Exception as e:
            flash(f"Database error: {e}", "danger")
            return redirect(request.url)

        try:
            git_commit_push(f"Upload and add PDF {pdf_filename}")
        except Exception as e:
            flash(f"Git push failed: {e}", "warning")

        flash(f"File '{filename}' uploaded and processed successfully!", "success")
        return redirect(url_for("index"))

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

    remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"

    subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True)
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", commit_message], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "batch":
        print("Batch mode not implemented in this version.")
    else:
        app.run(debug=True)
