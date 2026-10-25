# Deploy Chronicle frontend and API on Vercel

Chronicle can run with **two Vercel projects** connected to the same GitHub repository:

- `chronicle-research-web` — Next.js UI from `apps/web`
- `chronicle-research-api` — FastAPI backend from `services/api`
- Neon PostgreSQL — persistent relational storage (database provider remains Neon)

Vercel's Python runtime deploys the FastAPI app as a Function. This setup is suitable for a student-project demo, but it is not equivalent to a permanently running worker or a durable file-storage service.

## A. Create the API project

1. Open https://vercel.com/new and import `affanSkhan/chronicle`.
2. Name the project `chronicle-research-api`.
3. Set **Root Directory** to `services/api`.
4. Set the framework to FastAPI if prompted; otherwise use the detected Python/FastAPI configuration.
5. Leave Build Command and Output Directory at their detected defaults. The repository has `requirements.txt`, a root-level `index.py` exporting the FastAPI `app`, and `vercel.json` to set function duration.
6. Use Python 3.12. Deploy the project and note its production origin.

Configure these environment variables in Vercel Project Settings → Environment Variables for Production (and separately Preview/Development only if you intend to use those environments):

| Variable | Value |
|---|---|
| `APP_NAME` | `Chronicle API` |
| `APP_VERSION` | `0.1.0` |
| `ENVIRONMENT` | `production` |
| `API_PREFIX` | `/api/v1` |
| `DATABASE_URL` | Neon connection URL using the `postgresql+psycopg://` scheme |
| `JWT_SECRET_KEY` | A securely generated random secret of at least 32 characters |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `480` |
| `CORS_ORIGINS` | Exact production origin of the deployed frontend, e.g. `https://your-actual-web-domain.vercel.app` |
| `MAX_UPLOAD_MB` | `3` |
| `MAX_PDF_PAGES` | `300` |
| `UPLOAD_DIR` | `/tmp/chronicle-uploads` |
| `ENABLE_SCHEDULED_MONITORING` | `false` |
| `SOURCE_MONITOR_POLL_SECONDS` | `60` |
| `SOURCE_MONITOR_BATCH_SIZE` | `20` |

For model-assisted extraction and synthesis without paid API usage, configure the API project with Groq's free tier:
- `LLM_API_KEY`: create a key at https://console.groq.com/keys
- `LLM_API_BASE=https://api.groq.com/openai/v1`
- `LLM_MODEL=openai/gpt-oss-20b`

No paid credits or payment method are needed. Free-tier limits apply, and the app bounds prompt sizes and outputs to help fit them. Google Gemini's free tier is another option using `LLM_API_BASE=https://generativelanguage.googleapis.com/v1beta/openai/` plus a current free model ID and Google AI Studio key; Google may use free-tier content to improve products. Keep all keys server-side. Legacy `OPENAI_*` settings remain supported, but OpenAI API usage is billed separately from ChatGPT.

For more reliable scholarly discovery and source-status checks, add `OPENALEX_API_KEY` as a **Sensitive** API-project environment variable. Create a free key at [OpenAlex Settings → API key](https://openalex.org/settings/api). Chronicle sends this token only in the Authorization header to OpenAlex; it is not sent to Crossref. Save the secret and redeploy the API after adding it.

### Database migrations

Do not run schema migrations in every Vercel build: preview builds may point at the same production database, and concurrent builds can race. Instead, use the repository's manual GitHub Actions workflow:

1. In GitHub repository Settings → Secrets and variables → Actions, add or verify the repository secret `CHRONICLE_DATABASE_URL`. It should contain the same Neon database URL, kept secret.
2. Open Actions → **Database Migrations** → Run workflow and select branch `feat/srs-research-planning-verification` in the branch selector. **Do not dispatch this migration from `main` before PR #3 is merged:** `main` is still at migration `0005_source_monitoring` and does not contain migrations `0006` and `0007`.
3. Enter `APPLY` in the confirmation field and run the workflow.
4. Confirm the workflow ends successfully and the database `alembic_version` is `0007_run_cancel_retry` before exercising the new workspace/run-lifecycle endpoints.

The workflow runs `alembic upgrade head` against that secret. It normalizes a standard `postgresql://` or `postgres://` URL to the project's Psycopg 3 driver scheme without printing the connection credentials.

## Release gate for the SRS lifecycle branch

Before promoting the SRS lifecycle changes, confirm API, web and container CI are green on the pull request head. Dispatch the database migration workflow from `feat/srs-research-planning-verification` as described above, not from the older `main` branch. The production database must report Alembic revision `0007_run_cancel_retry` before Vercel production receives the new API code.

After merge, verify the new production deployment is READY and points to the merge SHA. Use the actual production aliases (not a preview URL) to test registration/login, source search, workspace create/rename/archive/restore, runs in all four research modes, PDF ingestion, model-assisted claim verification when a model is configured, dependency review, source-event impact propagation, report-version history, and Markdown/JSON/PDF Evidence Passport downloads. Test a second user to confirm private records remain isolated. The health endpoint is a liveness check only; successful health output does not prove database or optional AI-provider configuration is correct.

## B. Create the frontend project

1. In https://vercel.com/new, import `affanSkhan/chronicle` again as a **second** project.
2. Name it `chronicle-research-web`.
3. Set **Root Directory** to `apps/web`.
4. Set Framework Preset to `Next.js`, Node.js Version to `22.x`, Install Command to `npm install`, Build Command to `npm run build`, and leave Output Directory at the default.
5. Add this environment variable in Project Settings → Environment Variables:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | The API project's production origin only, such as `https://your-actual-api-domain.vercel.app` |

Do not append `/api/v1` or a trailing slash. The UI assembles the API paths itself. Redeploy the frontend after saving environment variables.

## C. Finish the connection and verify

1. Copy the frontend's actual production origin from Vercel and set it exactly in the API project's `CORS_ORIGINS` variable. Save and redeploy the API.
2. Check the API migration workflow is green and the database Alembic revision matches the current branch.
3. Check `https://YOUR-API-DOMAIN/api/v1/health` for process liveness and `https://YOUR-API-DOMAIN/api/v1/ready` for database readiness. The readiness response should include `status: ready` and `dependencies.database: ok`; a failed database check returns HTTP 503 without leaking connection details.
4. In the frontend, test registration/login, academic source search, workspace lifecycle, all four research modes, PDF ingestion, source-event impact propagation, report history, and Markdown/JSON/PDF Evidence Passport downloads. Verify private records remain isolated across two accounts.

Both projects can auto-deploy on pushes to `main`. Ensure the GitHub import is authorized for the `affanSkhan/chronicle` repository.

## Vercel-specific limitations in the current prototype

- **PDF request size:** Vercel Functions impose a 4.5 MB request/response payload limit. Chronicle currently uploads PDFs through the API, so `MAX_UPLOAD_MB=3` is a safe starting setting. To support large PDFs, change the upload flow to send files directly to object storage (e.g. Vercel Blob) and have the API process them by object reference.
- **File durability:** Chronicle writes original PDFs to the API filesystem. `/tmp` is temporary and is not durable storage across Function invocations. Extracted passages and relational metadata in Neon persist, but original PDF storage needs an object-storage integration to be durable.
- **Function lifetime:** FastAPI runs as a Vercel Function, not as an always-on server. Request-triggered work must complete within the configured function duration. Long-running/durable jobs should be moved to a queue/worker design.
- **Scheduled monitoring:** Keep the API's in-process scheduler disabled on Vercel. The repository's GitHub Actions source-monitor workflow is the better fit for scheduled polling, using `CHRONICLE_DATABASE_URL`.
- **Database:** The application runtime is on Vercel, but PostgreSQL remains hosted by Neon. Use a connection URL and pool strategy supported by your Neon project; do not use SQLite or store relational data on the function filesystem.

Official references:
- https://vercel.com/docs/frameworks/backend/fastapi
- https://vercel.com/docs/monorepos
- https://vercel.com/docs/functions/limitations
- https://vercel.com/docs/vercel-blob/server-upload
