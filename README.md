# NMIT-GPT

NMIT-GPT is an AI-powered assistant for students and faculty at NMIT.

It combines retrieval-augmented generation (RAG), structured database queries,
and LLM-based natural-language understanding to answer questions about
academic information.

## Features

- Student and faculty chatbot with JWT authentication
- Faculty information and subject queries
- Class timetables and lab availability
- Academic calendar and circular retrieval
- Admin dashboard for managing academic information
- AI-assisted timetable PDF extraction with manual review
- Validated, atomic timetable saving to Supabase
- Compatibility with legacy and 24-hour timetable formats

## Technology

- Python and FastAPI
- PostgreSQL via Supabase
- Ollama for local LLM inference
- Sentence Transformers for embeddings
- HTML, CSS, and JavaScript frontend
- JWT authentication and role-based access control

## Project Structure

- `backend/` - FastAPI routes, authentication, and timetable extraction
- `RAG_ENGINE/` - Query parsing, retrieval, and answer generation
- `frontend/` - Student chatbot and admin dashboard
- `data_pipeline/` - Data ingestion and processing
- `database/` - Timetable database functions and SQL scripts
- `tests/` - Automated regression tests

## Development

Install dependencies from `requirements.txt` and configure environment
variables locally. Never commit `.env` files or API credentials.

Local LLM features require an accessible Ollama service and the relevant
models installed.

## Deployment

Cloud deployment requires an accessible LLM inference endpoint.
A cloud-hosted FastAPI service cannot automatically access Ollama running
on a developer's computer.

Configure database credentials, JWT secrets, frontend API URL, and CORS
origins before deploying.

## Verification

The timetable integration has been tested through admin PDF extraction,
review, Supabase staging save, and database read-back.

The source branch passed 55 automated regression tests before integration.
