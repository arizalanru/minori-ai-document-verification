# Railway demo deployment

This deployment is only for synthetic demonstration data. Do not upload real
participant documents.

## Required Railway variables

- `GEMINI_API_KEY`
- `GEMINI_MODEL=gemini-3.1-flash-lite`
- `DEMO_ACCESS_USERNAME`
- `DEMO_ACCESS_PASSWORD`
- `DATABASE_PATH=/app/var/app.sqlite3`
- `PRIVATE_FILES_DIR=/app/var/files`

Both demo access variables are required together. When configured, every route
except `/api/v1/health` is protected with browser HTTP Basic authentication.

## Persistent volume

Create one Railway volume and mount it at:

```text
/app/var
```

The volume stores SQLite data and uploaded synthetic images across deploys.

## Deployment checklist

1. Create a Railway project from this GitHub repository.
2. Deploy with the included `Dockerfile` and `railway.toml`.
3. Add all required variables using Railway's Variables page.
4. Mount a persistent volume at `/app/var`.
5. Generate a public domain only after authentication is configured.
6. Open `/api/v1/health` and verify a successful response.
7. Sign in to the root page using the demo credentials.
8. Run one synthetic document test and monitor memory, build time, and logs.
9. Share credentials privately with the reviewer; never commit them.

The PaddleOCR image is larger than a typical FastAPI deployment. Allocate enough
memory for model initialization and expect the first OCR request to be slower.
