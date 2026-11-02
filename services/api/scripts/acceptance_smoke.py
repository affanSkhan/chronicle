"""Run a small authenticated acceptance flow against a deployed Chronicle API.

The script creates a temporary account, exercises health/readiness, authentication,
workspace CRUD, a non-executing research run, and permanent workspace deletion.
It never prints credentials or response bodies.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import uuid

import httpx


def request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    expected: int,
    **kwargs: object,
) -> httpx.Response:
    response = client.request(method, path, **kwargs)
    if response.status_code != expected:
        raise RuntimeError(f"{method} {path} returned {response.status_code}; expected {expected}.")
    return response


def json_payload(response: httpx.Response, path: str) -> dict:
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        location = response.headers.get("location")
        suffix = f" Redirect: {location}" if location else ""
        raise RuntimeError(
            f"{path} returned non-JSON content type {content_type or 'unknown'} "
            f"(status {response.status_code}).{suffix} "
            "Disable Vercel Deployment Protection for the target or run with an authorized deployment URL."
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} returned a non-object JSON payload.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Chronicle deployed API acceptance smoke checks.")
    parser.add_argument("--base-url", default=os.environ.get("CHRONICLE_API_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--email", default=os.environ.get("CHRONICLE_SMOKE_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("CHRONICLE_SMOKE_PASSWORD"))
    parser.add_argument("--insecure-http", action="store_true", help="Allow an HTTP base URL for local testing.")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    if base_url.startswith("http://") and not args.insecure_http:
        raise RuntimeError("Refusing HTTP for acceptance checks; use HTTPS or --insecure-http locally.")
    email = args.email or f"chronicle-smoke-{uuid.uuid4().hex[:12]}@example.invalid"
    password = args.password or secrets.token_urlsafe(18)

    with httpx.Client(base_url=base_url, timeout=30, follow_redirects=True) as client:
        health = request(client, "GET", "/api/v1/health", expected=200)
        if json_payload(health, "/api/v1/health").get("status") != "ok":
            raise RuntimeError("Health endpoint did not report status=ok.")
        ready = request(client, "GET", "/api/v1/ready", expected=200)
        if json_payload(ready, "/api/v1/ready").get("status") != "ready":
            raise RuntimeError("Readiness endpoint did not report status=ready.")
        if health.headers.get("x-content-type-options") != "nosniff":
            raise RuntimeError("Security response headers are missing.")

        auth = request(
            client,
            "POST",
            "/api/v1/auth/register",
            expected=201,
            json={"email": email, "password": password},
        )
        auth_payload = json_payload(auth, "/api/v1/auth/register")
        token = auth_payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("Registration did not return an access token.")
        client.headers["Authorization"] = f"Bearer {token}"
        request(client, "GET", "/api/v1/auth/me", expected=200)

        project = json_payload(request(
            client,
            "POST",
            "/api/v1/projects",
            expected=201,
            json={
                "title": "Deployment acceptance workspace",
                "research_question": "How can deployed evidence workflows remain inspectable?",
            },
        ), "/api/v1/projects")
        project_id = project["id"]
        request(
            client,
            "PATCH",
            f"/api/v1/projects/{project_id}",
            expected=200,
            json={"title": "Deployment acceptance workspace renamed"},
        )
        run = json_payload(request(
            client,
            "POST",
            "/api/v1/research/runs",
            expected=201,
            json={
                "project_id": project_id,
                "question": "How should a deployed evidence workflow be tested?",
                "mode": "quick",
                "execute": False,
            },
        ), "/api/v1/research/runs")
        if run.get("status") != "queued" or run.get("demo") is not True:
            raise RuntimeError("Research run lifecycle response was unexpected.")
        request(client, "GET", "/api/v1/research/runs", expected=200)
        request(client, "DELETE", f"/api/v1/projects/{project_id}", expected=204)
        request(client, "GET", f"/api/v1/projects/{project_id}", expected=404)

    print(f"Chronicle acceptance smoke passed for {base_url}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"Acceptance smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
