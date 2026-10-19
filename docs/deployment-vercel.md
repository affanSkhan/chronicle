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

For optional model-assisted extraction and synthesis, add `OPENAI_API_KEY`, `OPENAI_API_BASE=https://api.openai.com/v1`, and `OPENAI_MODEL` on the API project only. Keep database/JWT/model credentials out of frontend environment variables and source control.

### Database migrations

Do not run schema migrations in every Vercel build: preview builds may point at the same production database, and concurrent builds can race. Instead, use the repository's manual GitHub Actions workflow:

1. In GitHub repository Settings → Secrets and variables → Actions, add or verify the repository secret `CHRONICLE_DATABASE_URL`. It should contain the same Neon database URL, kept secret.
2. Open Actions → **Database Migrations** → Run workflow.
3. Enter `APPLY` in the confirmation field and run the workflow.
4. Confirm the workflow ends successfully before exercising database-backed endpoints.

The workflow runs `alembic upgrade head` against that secret. It normalizes a standard `postgresql://` or `postgres://` URL to the project's Psycopg 3 driver scheme without printing the connection credentials.

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
2. Check `https://YOUR-API-DOMAIN/api/v1/health` returns a successful health response.
3. Check the API migration workflow is green.
4. In the frontend, test registration, login, academic source search, project/run creation, and evidence retrieval.

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
