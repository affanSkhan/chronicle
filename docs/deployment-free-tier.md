# Free-tier deployment runbook

## Recommended demo topology

- **Frontend + API:** separate Render Free web services declared in the repository root `render.yaml`.
- **Database:** the dedicated Neon PostgreSQL project `chronicle-research`, in AWS Singapore. Use the existing database `chronicle` and role `chronicle_app`.
- **Recurring status checks:** GitHub Actions workflow `.github/workflows/source-monitor.yml` runs hourly; add the database URL as a repository Actions secret to activate it.
- **AI synthesis:** optional. Add `OPENAI_API_KEY` and `OPENAI_MODEL` to the API service later if model-assisted extraction is required.

This is a **free-tier demo deployment**, not a production/SLA deployment. Render Free services sleep after idle time and have ephemeral filesystems; Neon Free has scale-to-zero and finite quotas. Chronicle's relational records (accounts, runs, paper metadata, extracted passages, audit trail) are stored in Neon, but original uploaded PDF files are currently written to the API filesystem and may disappear after a Render restart/redeploy/spin-down. Do not use it as long-term archival storage until private object storage is implemented. See the provider limits linked at the bottom of this document.

## 1. Create the Render Blueprint

1. Open the [Render dashboard](https://dashboard.render.com/).
2. Select **New → Blueprint** and connect `affanSkhan/chronicle` on branch `main`.
3. Render reads the root `render.yaml` and proposes two services: `chronicle-research-api` and `chronicle-research-web`.
4. In the initial Blueprint prompt, supply `DATABASE_URL` for the API service from the Neon console. Choose the direct (non-pooled) connection string; change its scheme from `postgresql://` to `postgresql+psycopg://` so it matches the Python driver installed in this repo. Preserve the query parameters including `sslmode=require`.
5. Keep the generated `JWT_SECRET_KEY`; Render will generate a strong value for you.
6. Review the resource plan before applying. Both web services are configured as Free in Singapore. The blueprint does not create a second database.

The API's start command runs `alembic upgrade head` before starting FastAPI. Check the Render deploy logs for successful migration completion, then open `https://<api-service-host>/api/v1/health`. The frontend's public API URL and API CORS origin are wired from Render's external service URLs.

## 2. Enable recurring source monitoring

The API's in-process scheduler remains **disabled** in this free-tier Blueprint because free web services can sleep. The GitHub Actions workflow is the independent hourly scheduler.

1. Open repository Settings → Secrets and variables → Actions → New repository secret.
2. Name it `CHRONICLE_DATABASE_URL`.
3. Set its value to the same SQLAlchemy-compatible Neon connection string used by the API service. Keep it secret; do not commit it to `.env.example`, `render.yaml`, issues or source files.
4. Open Actions → Scheduled Source Monitoring and run it once using **Run workflow** to verify the runner configuration.

If the secret is absent, the workflow logs a notice and skips checks. Metadata provider signals are saved as review alerts; they do not automatically change a paper's publication status or create a source event. GitHub's scheduled workflows can be delayed, so checks should not be treated as real-time surveillance.

## 3. Optional model-assisted synthesis

In the API service's Render environment settings, add:
- `OPENAI_API_KEY` (secret)
- `OPENAI_MODEL` (the model ID available to your key)

`OPENAI_API_BASE` defaults to the OpenAI-compatible API base. Leave synthesis disabled until a key/model is configured; scholarly metadata retrieval and evidence-record workflows can still run in retrieval-only mode.

## 4. Operational limitations to accept before using

- Free Render web services spin down after 15 minutes without inbound traffic, and local filesystem changes are lost on restart/redeploy/spin-down.
- Neon Free provides limited compute/storage/transfer quotas and scales idle compute to zero.
- The current scheduled workflow checks up to the configured batch each hour. It is not publisher-complete, and coverage depends on Crossref/OpenAlex metadata being present.
- The research executor still uses FastAPI background tasks, not a durable task queue. Long research runs can be interrupted by a restart.
- Before real users rely on this system, implement private durable object storage for original PDFs, a reviewed cookie/session model, rate limiting, backups/restore tests, monitoring, and a comprehensive security review.

## Official provider documentation

- [Render free deployment limitations](https://render.com/docs/free)
- [Render Blueprint YAML reference](https://render.com/docs/blueprint-spec)
- [Neon Free plan quotas](https://neon.com/blog/neon-free-plan-1-gb-per-project)
