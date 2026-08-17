# Database

Void Radar uses PostgreSQL/Supabase as the canonical store for companies,
founders, provenance, research, signals, opportunities, scores, contacts,
outreach state, and feedback history.

Apply migrations in order from `database/migrations/`.

For a local PostgreSQL database:

```bash
psql "$DATABASE_URL" -f database/migrations/0001_core_schema.sql
```

Supabase projects can run the same SQL in the SQL editor or through the
Supabase CLI once the project is connected.

