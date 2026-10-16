import csv
import io
import json
import os
import re
import uuid
import csv
import io
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
import sqlite3

import ollama
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from pypdf import PdfReader
from werkzeug.utils import secure_filename


# --------------------------------------------------
# 1. CONFIGURATION
# --------------------------------------------------

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
INSTANCE_DIR = BASE_DIR / "instance"
DB_PATH = INSTANCE_DIR / "localledger.db"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "local-development-key-change-before-deployment",
)

max_upload_mb = int(os.getenv("MAX_CONTENT_LENGTH_MB", "10"))
app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024

MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf"}

ALLOWED_CATEGORIES = {
    "Food",
    "Groceries",
    "Travel",
    "Shopping",
    "Bills",
    "Healthcare",
    "Education",
    "Other",
}


# --------------------------------------------------
# 2. DATABASE
# --------------------------------------------------

def get_db():
    """Create a SQLite connection with dictionary-like rows."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    """Create the expenses table if it doesn't exist."""
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor TEXT NOT NULL DEFAULT 'Unknown',
                date TEXT NOT NULL DEFAULT '',
                subtotal REAL,
                tax REAL,
                total REAL,
                currency TEXT NOT NULL DEFAULT 'INR',
                category TEXT NOT NULL DEFAULT 'Other',
                source_file TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)


# --------------------------------------------------
# 3. FILE VALIDATION AND PDF TEXT EXTRACTION
# --------------------------------------------------

def allowed_file(filename):
    """Check whether the file has a supported extension."""
    return (
        bool(filename)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def extract_pdf_text(file_path):
    """Extract selectable text from a PDF."""
    reader = PdfReader(str(file_path))

    pages = []

    for page in reader.pages:
        pages.append(page.extract_text() or "")

    return "\n".join(pages).strip()


# --------------------------------------------------
# 4. AI RESPONSE PARSING
# --------------------------------------------------

def parse_ai_json(content):
    """Parse JSON returned by the local AI model."""
    content = content.strip()

    # Remove optional Markdown code fences.
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)

        if not match:
            raise ValueError(
                "The AI did not return valid JSON. Please try again."
            )

        data = json.loads(match.group(0))

    if not isinstance(data, dict):
        raise ValueError("The AI response must be a JSON object.")

    return data


# --------------------------------------------------
# 5. RECEIPT DATA EXTRACTION USING OLLAMA
# --------------------------------------------------

def extract_expense(file_path, extension):
    """Extract structured expense details using the local AI model."""

    prompt = """
You extract expense information from receipts and invoices.

Return ONLY one valid JSON object with these exact keys:
{
  "vendor": "merchant name or Unknown",
  "date": "YYYY-MM-DD or empty string",
  "subtotal": number or null,
  "tax": number or null,
  "total": number or null,
  "currency": "three-letter currency code or Unknown",
  "category": "Food, Groceries, Travel, Shopping, Bills, Healthcare, Education, or Other"
}

Rules:
- Do not invent missing information.
- Use null for unknown monetary amounts.
- Amounts must be JSON numbers, without currency symbols or commas.
- Use the final amount payable as total when clearly shown.
- Convert dates to YYYY-MM-DD only when the date is unambiguous.
- Identify the currency from the receipt's currency symbol or code.
- Use Groceries for grocery-store purchases when appropriate.
- Use Food for restaurants, cafes, and prepared meals.
- Choose the closest category based on the receipt.
- Return JSON only. Do not include explanations.
"""

    if extension == "pdf":
        receipt_text = extract_pdf_text(file_path)

        if not receipt_text:
            raise ValueError(
                "This PDF has no selectable text. Scanned PDF OCR "
                "is not supported yet. Try uploading a receipt image."
            )

        response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": (
                        prompt
                        + "\n\nReceipt text:\n"
                        + receipt_text[:15000]
                    ),
                }
            ],
            format="json",
        )

    else:
        response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                    "images": [str(file_path)],
                }
            ],
            format="json",
        )

    content = response["message"]["content"]
    data = parse_ai_json(content)

    def amount_or_none(value):
        if value is None or value == "":
            return None

        # Reject booleans, which Python otherwise treats as numbers.
        if isinstance(value, bool):
            return None

        try:
            amount = float(value)

            if not (amount >= 0 and amount < float("inf")):
                return None

            return round(amount, 2)

        except (ValueError, TypeError, OverflowError):
            return None

    vendor = str(data.get("vendor") or "Unknown").strip()
    date = str(data.get("date") or "").strip()
    currency = str(data.get("currency") or "INR").strip().upper()
    category = str(data.get("category") or "Other").strip()

    # Normalize common category variations.
    category_lower = category.lower()

    if category_lower in {"grocery", "groceries", "supermarket"}:
        category = "Groceries"
    elif category_lower in {"restaurant", "cafe", "food and drink"}:
        category = "Food"
    elif category_lower not in {item.lower() for item in ALLOWED_CATEGORIES}:
        category = "Other"
    else:
        category = next(
            item for item in ALLOWED_CATEGORIES
            if item.lower() == category_lower
        )

    # Keep only valid ISO dates. Ambiguous dates are left blank.
    if date:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            date = ""

    # Currency should be a three-letter code.
    if not re.fullmatch(r"[A-Z]{3}", currency):
        currency = "INR"

    return {
        "vendor": vendor[:200] or "Unknown",
        "date": date,
        "subtotal": amount_or_none(data.get("subtotal")),
        "tax": amount_or_none(data.get("tax")),
        "total": amount_or_none(data.get("total")),
        "currency": currency,
        "category": category,
    }


# --------------------------------------------------
# 6. DASHBOARD
# --------------------------------------------------

@app.route("/")
def index():
    with get_db() as db:
        expenses = db.execute(
            "SELECT * FROM expenses ORDER BY id DESC"
        ).fetchall()

    # Only combine INR expenses in INR analytics.
    inr_expenses = [
        expense for expense in expenses
        if expense["currency"] == "INR"
    ]

    total_spent = sum(
        expense["total"] or 0
        for expense in inr_expenses
    )

    # Current month spending.
    now = datetime.now()
    current_month = now.strftime("%Y-%m")

    current_month_expenses = [
        expense for expense in inr_expenses
        if expense["date"]
        and expense["date"].startswith(current_month)
    ]

    current_month_spent = sum(
        expense["total"] or 0
        for expense in current_month_expenses
    )

    average_expense = (
        total_spent / len(inr_expenses)
        if inr_expenses else 0
    )

    # Spending grouped by category.
    category_totals = {}

    for expense in inr_expenses:
        category = expense["category"] or "Other"
        category_totals[category] = (
            category_totals.get(category, 0)
            + (expense["total"] or 0)
        )

    category_analytics = sorted(
        [
            {
                "category": category,
                "total": round(amount, 2),
                "percentage": (
                    round((amount / total_spent) * 100, 1)
                    if total_spent else 0
                ),
            }
            for category, amount in category_totals.items()
        ],
        key=lambda item: item["total"],
        reverse=True,
    )

    # Last six months, including months with zero spending.
    monthly_analytics = []

    for offset in range(5, -1, -1):
        month_date = now.replace(day=1)

        month_number = month_date.month - offset
        year = month_date.year

        while month_number <= 0:
            month_number += 12
            year -= 1

        month_key = f"{year:04d}-{month_number:02d}"

        month_total = sum(
            expense["total"] or 0
            for expense in inr_expenses
            if expense["date"]
            and expense["date"].startswith(month_key)
        )

        monthly_analytics.append({
            "month": datetime.strptime(
                month_key, "%Y-%m"
            ).strftime("%b %Y"),
            "total": round(month_total, 2),
        })

    max_monthly_spending = max(
        (item["total"] for item in monthly_analytics),
        default=0,
    )

    return render_template(
        "index.html",
        expenses=expenses,
        total_spent=total_spent,
        expense_count=len(expenses),
        model=MODEL,
        current_month_spent=current_month_spent,
        average_expense=average_expense,
        category_analytics=category_analytics,
        monthly_analytics=monthly_analytics,
        max_monthly_spending=max_monthly_spending,
    )


# --------------------------------------------------
# 7. UPLOAD AND REVIEW RECEIPT
# --------------------------------------------------

@app.route("/upload", methods=["POST"])
def upload():
    uploaded = request.files.get("receipt")

    if not uploaded or not uploaded.filename:
        flash("Please choose a receipt image or PDF.", "error")
        return redirect(url_for("index"))

    if not allowed_file(uploaded.filename):
        flash(
            "Supported formats: PNG, JPG, JPEG, WEBP and PDF.",
            "error",
        )
        return redirect(url_for("index"))

    original_name = secure_filename(uploaded.filename)

    if not original_name or "." not in original_name:
        flash("The filename is invalid.", "error")
        return redirect(url_for("index"))

    extension = original_name.rsplit(".", 1)[1].lower()

    saved_name = f"{uuid.uuid4().hex}.{extension}"
    file_path = UPLOAD_DIR / saved_name

    try:
        uploaded.save(file_path)

        # Run AI extraction.
        expense = extract_expense(file_path, extension)

        # Keep the filename for display and recordkeeping only.
        expense["source_file"] = original_name

        # Do not save to SQLite yet.
        # Let the user review the extracted values first.
        return render_template(
            "review.html",
            expense=expense,
        )

    except Exception:
        app.logger.exception("Receipt processing failed")

        flash(
            "Could not process this receipt. Check that Ollama is "
            "running, the configured model is installed, and the "
            "receipt is readable. See the terminal for details.",
            "error",
        )

        return redirect(url_for("index"))

    finally:
        # Delete the uploaded original after extraction.
        # The review page contains the extracted fields, not the image.
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                app.logger.warning(
                    "Could not remove temporary upload: %s",
                    file_path.name,
                )


# --------------------------------------------------
# 8. VALIDATE AND SAVE REVIEWED EXPENSE
# --------------------------------------------------

@app.route("/save", methods=["POST"])
def save_expense():
    def read_amount(field):
        value = request.form.get(field, "").strip()

        if not value:
            return None

        try:
            amount = float(value)

            if not (amount >= 0 and amount < float("inf")):
                raise ValueError

            return round(amount, 2)

        except (ValueError, TypeError, OverflowError):
            raise ValueError(
                f"{field.title()} must be a valid non-negative number."
            )

    try:
        vendor = request.form.get("vendor", "").strip()
        date = request.form.get("date", "").strip()
        currency = request.form.get("currency", "").strip().upper()
        category = request.form.get("category", "").strip()
        source_file = secure_filename(
            request.form.get("source_file", "").strip()
        )

        if not vendor or len(vendor) > 200:
            raise ValueError(
                "Vendor must contain between 1 and 200 characters."
            )

        if date:
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                raise ValueError(
                    "Please enter a valid date in YYYY-MM-DD format."
                )

        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError(
                "Currency must be a three-letter code, such as USD or INR."
            )

        if category not in ALLOWED_CATEGORIES:
            raise ValueError("Please choose a valid category.")

        subtotal = read_amount("subtotal")
        tax = read_amount("tax")
        total = read_amount("total")

        with get_db() as db:
            db.execute(
                """
                INSERT INTO expenses (
                    vendor,
                    date,
                    subtotal,
                    tax,
                    total,
                    currency,
                    category,
                    source_file,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vendor,
                    date,
                    subtotal,
                    tax,
                    total,
                    currency,
                    category,
                    source_file[:255],
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

        flash("Expense reviewed and saved successfully!", "success")

    except ValueError as error:
        flash(f"Please check the expense details: {error}", "error")
        return redirect(url_for("index"))

    except sqlite3.Error:
        app.logger.exception("Database save failed")
        flash("The expense could not be saved to the database.", "error")
        return redirect(url_for("index"))

    return redirect(url_for("index"))


# --------------------------------------------------
# 9. EXPORT EXPENSES TO CSV
# --------------------------------------------------

@app.route("/export")
def export_csv():
    with get_db() as db:
        expenses = db.execute(
            """
            SELECT
                vendor,
                date,
                subtotal,
                tax,
                total,
                currency,
                category,
                source_file,
                created_at
            FROM expenses
            ORDER BY id DESC
            """
        ).fetchall()

    output = io.StringIO(newline="")
    writer = csv.writer(output)

    writer.writerow(
        [
            "Vendor",
            "Date",
            "Subtotal",
            "Tax",
            "Total",
            "Currency",
            "Category",
            "Source file",
            "Created at",
        ]
    )

    for expense in expenses:
        writer.writerow(tuple(expense))

    memory_file = io.BytesIO(
        output.getvalue().encode("utf-8-sig")
    )
    memory_file.seek(0)

    return send_file(
        memory_file,
        mimetype="text/csv",
        as_attachment=True,
        download_name="localledger-expenses.csv",
    )


# --------------------------------------------------
# 10. ERROR HANDLERS
# --------------------------------------------------

@app.errorhandler(413)
def file_too_large(_error):
    flash(
        f"File is too large. The upload limit is {max_upload_mb} MB.",
        "error",
    )
    return redirect(url_for("index"))


# --------------------------------------------------
# 11. START APPLICATION
# --------------------------------------------------

init_db()

if __name__ == "__main__":
    app.run(debug=True)
