# Deploy Chronicle frontend and API on Vercel

Chronicle can run with **two Vercel projects** connected to the same GitHub repository:

- `chronicle-research-web` — Next.js UI from `apps/web` (production alias: https://chronicle-research-web.vercel.app)
- `chronicle` — FastAPI backend from `services/api` (production alias: https://chronicle-affan-27c6.vercel.app)
- Neon PostgreSQL — persistent relational storage (database provider remains Neon)

Vercel's Python runtime deploys the FastAPI app as a Function. This setup is suitable for a student-project demo, but it is not equivalent to a permanently running worker or a durable file-storage service.

## A. Create the API project

1. Open https://vercel.com/new and import `affanSkhan/chronicle`.
2. The existing connected API project is named `chronicle`; reuse it rather than creating a second API project.
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
| `HF_TOKEN` | Optional Hugging Face token with Inference Providers permission; store as Sensitive |
| `HF_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` |
| `HF_EMBEDDING_API_BASE` | `https://router.huggingface.co/hf-inference/models` |
| `OBJECT_STORAGE_ENDPOINT_URL` | Preferred private S3-compatible endpoint for original PDFs; optional after migration 0008 because a private PostgreSQL blob fallback is available (3 MB Vercel cap) |
| `OBJECT_STORAGE_BUCKET` | Private bucket name |
| `OBJECT_STORAGE_ACCESS_KEY_ID` | Sensitive object-storage credential |
| `OBJECT_STORAGE_SECRET_ACCESS_KEY` | Sensitive object-storage credential |
| `OBJECT_STORAGE_REGION` | Region value accepted by your S3-compatible provider, or `auto` where supported |
| `OBJECT_STORAGE_PREFIX` | `chronicle-private` |

For model-assisted extraction and synthesis without paid API usage, configure the API project with Groq's free tier:
- `LLM_API_KEY`: create a key at https://console.groq.com/keys
- `LLM_API_BASE=https://api.groq.com/openai/v1`
- `LLM_MODEL=openai/gpt-oss-20b`

No paid credits or payment method are needed. Free-tier limits apply, and the app bounds prompt sizes and outputs to help fit them. Google Gemini's free tier is another option using `LLM_API_BASE=https://generativelanguage.googleapis.com/v1beta/openai/` plus a current free model ID and Google AI Studio key; Google may use free-tier content to improve products. Keep all keys server-side. Legacy `OPENAI_*` settings remain supported, but OpenAI API usage is billed separately from ChatGPT.

For more reliable scholarly discovery and source-status checks, add `OPENALEX_API_KEY` as a **Sensitive** API-project environment variable. Create a free key at [OpenAlex Settings → API key](https://openalex.org/settings/api). Chronicle sends this token only in the Authorization header to OpenAlex; it is not sent to Crossref. Save the secret and redeploy the API after adding it.

For semantic passage retrieval, configure `HF_TOKEN` as a Sensitive variable. The current implementation uses the Hugging Face feature-extraction endpoint and combines dense ranks with a bounded BM25 shortlist using reciprocal rank fusion. Hugging Face Inference Providers has a free tier but availability and quotas depend on the current model/provider; no token means the application remains in BM25-only mode. See [feature extraction docs](https://huggingface.co/docs/inference-providers/en/tasks/feature-extraction). Retrieval rankings are not calibrated evidence-confidence scores.

For preferred private PDF object storage, configure all `OBJECT_STORAGE_*` values together for an S3-compatible private bucket. After migration `0008_persistent_pdf_content`, production/serverless uses the separate `uploaded_pdf_blobs` PostgreSQL table when the bucket is not configured; originals no longer rely on the ephemeral function filesystem. Vercel API uploads are capped at 3 MB until direct-to-object-storage uploads are implemented. Do not put credentials in GitHub or client-side environment variables.

### Database migrations

Do not run schema migrations in every Vercel build: preview builds may point at the same production database, and concurrent builds can race. Use the repository's manual GitHub Actions **Database Migrations** workflow only when the release includes new Alembic migration files. Provide the repository secret `CHRONICLE_DATABASE_URL` and dispatch the workflow against the exact release branch; confirm its successful completion and the expected `alembic_version` before deploying code that depends on the new schema.

The final FF180 hardening PR adds migration `0008_persistent_pdf_content`, which creates the separate private `uploaded_pdf_blobs` table. Apply it through the manual Database Migrations workflow after review and before deploying code that can use the database fallback. A schema inspection on 2026-10-29 showed the connected Neon database did not yet have this table. Never run schema migrations automatically during a Vercel build.

## Release gate for this completion branch

Before release, require API CI, web CI, and container CI to pass for the exact branch head. Confirm migration 0008 is applied and the `uploaded_pdf_blobs` table exists. Merge only after reviewing the PR diff and checks. The existing Git integration should create the production deployments; verify both deployments are `READY` and point at the merge SHA.

Use the actual production aliases (not preview URLs) to smoke-test registration/login, source search, workspace create/rename/archive/restore, all four research modes, selected-PDF-to-run retrieval, citation review, dependency review, source-event impact propagation, report history, Markdown/JSON/PDF Evidence Passport downloads, and permanent PDF deletion/redaction. Test with a second account. The health endpoint is a liveness check only; successful health output does not prove database or optional AI-provider configuration is correct. Confirm the optional `HF_TOKEN` and `OBJECT_STORAGE_*` values are set only if you intend to enable dense retrieval and durable originals, respectively.

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
- **File durability:** Chronicle supports a private S3-compatible storage adapter when all `OBJECT_STORAGE_*` variables are configured. Without them, original PDFs fall back to the filesystem and are explicitly marked non-durable on serverless runtimes. Extracted passages and relational metadata persist in Neon.
- **Function lifetime:** FastAPI runs as a Vercel Function, not as an always-on server. Request-triggered work must complete within the configured function duration. The code supports an optional PostgreSQL-backed queue and Docker worker profile, but this worker is not hosted on Vercel. Keep `RESEARCH_EXECUTION_MODE=inline` unless a separate worker is running continuously.
- **Scheduled monitoring:** Keep the API's in-process scheduler disabled on Vercel. The repository's GitHub Actions source-monitor workflow is the better fit for scheduled polling, using `CHRONICLE_DATABASE_URL`.
- **Database:** The application runtime is on Vercel, but PostgreSQL remains hosted by Neon. Use a connection URL and pool strategy supported by your Neon project; do not use SQLite or store relational data on the function filesystem.

Official references:
- https://vercel.com/docs/frameworks/backend/fastapi
- https://vercel.com/docs/monorepos
- https://vercel.com/docs/functions/limitations
- https://vercel.com/docs/vercel-blob/server-upload

## FF180 completion-branch operational guardrails

- Do not promote a branch preview to production solely because its build is READY. Verify the exact commit, database readiness, API/web compatibility, and browser acceptance first.
- On Vercel, uploaded PDFs use private S3-compatible storage when configured, otherwise the PostgreSQL blob table after migration 0008. Verify an upload/read/delete round-trip. The API filesystem is not durable across serverless invocations. Keep the request upload cap at 3 MB until direct-to-object-storage uploads exist.
- Hugging Face dense retrieval is optional and disabled unless configured. BM25 remains the free, deterministic fallback; retrieval rank scores are not evidence-confidence scores.
- Re-verification after a source event is a user-triggered, bounded model-assisted review. It must keep the human-review flag and append audit history; it must not automatically label a claim false.
- Production deploy workflows are subject to Vercel plan/build-rate limits. A Vercel deployment status failure caused by quota is not evidence of a source-code test failure, and no plan upgrade is assumed.
