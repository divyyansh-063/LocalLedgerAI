# LocalLedger AI

**Turn receipts into organized expenses with local AI.**

LocalLedger AI is a privacy-focused receipt and invoice expense tracker built with Python, Flask, SQLite, and Gemma running locally through Ollama.

## The problem

Manually entering expenses from receipts takes time. Traditional expense tracking also requires users to type transaction details one field at a time, while sending receipts to cloud AI services may raise privacy and cost concerns.

## The solution

LocalLedger AI extracts expense information from uploaded receipts and invoices, lets users review and correct the extracted fields, and saves approved transactions to a local SQLite database.

## Features

- AI-assisted receipt and invoice extraction
- Review and edit extracted fields before saving
- Local SQLite expense storage
- Spending analytics by category and month
- CSV export for spreadsheet workflows
- Local inference through Ollama and Gemma

## Technology stack

- Python and Flask
- Gemma 3 running through Ollama
- SQLite
- HTML, CSS and JavaScript

## Run locally

1. Install Python and [Ollama](https://ollama.com/).
2. Pull the model used by the application:

   `ollama pull gemma3:4b`

3. Clone this repository and enter its directory.
4. Create and activate a Python virtual environment.
5. Install the dependencies listed in `requirements.txt`.
6. Start Ollama and run the Flask application:

   `python app.py`

7. Open `http://127.0.0.1:5000` in your browser.

Check the actual dependency list and application configuration before publishing these instructions.

## Privacy

Receipt extraction is designed to run locally through Ollama. Review your configuration before claiming that all processing and storage remain local. Do not upload private receipts or credentials to the public repository.

## Demo

Add a link to the project demonstration video here.

## Why open innovation matters

Using an open-weight model locally gives developers control over inference and provides an alternative to sending every receipt to a hosted AI service. This can help reduce per-request service costs and support privacy-conscious workflows, depending on the user's hardware and configuration.

## Current limitations

- Extraction accuracy depends on receipt image quality and model output.
- Users should verify extracted totals, dates, taxes and categories before saving.
- The current application is designed as a local prototype; multi-user access and production deployment require additional security work.

## License

MIT
