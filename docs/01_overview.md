# Odoo Data Migration - Overview

## Purpose

This project migrates data from **Odoo 11** to **Odoo 17**. Instead of using Odoo's built-in migration tools (which often leave garbage data and require complex upgrade scripts), this approach:

1. Connects to both Odoo instances via **OdooRPC**
2. Reads records from the source (Odoo 11)
3. Applies **transformations** to adapt data structures between versions
4. Creates/updates records in the destination (Odoo 17) via RPC
5. Maintains **tracking IDs** (`x_old_id` / `x_new_id`) for referential integrity

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           main.py                                    │
│  - Loads configuration (migration.conf)                             │
│  - Initializes logging                                              │
│  - Creates Migration executor instance                              │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       migration/executor.py                          │
│  - Orchestrates migration sequence                                  │
│  - Iterates through models_to_migrate list                          │
│  - Fetches records in batches (500 per batch)                       │
│  - Delegates to model-specific handlers                             │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       migration/handlers/                            │
│  - One handler per model (e.g., ProductTemplateHandler)             │
│  - apply_transformations(): Adapts Odoo 11 → Odoo 17 schema         │
│  - save_into_destination(): Creates/updates records via RPC         │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            ┌───────────┐   ┌───────────┐   ┌───────────┐
            │  core/    │   │  core/    │   │  core/    │
            │  odoo_    │   │  database │   │  mapping  │
            │connection │   │  .py      │   │  .py      │
            └───────────┘   └───────────┘   └───────────┘
```

## Key Components

### 1. Configuration (`migration.conf`)
- **[source]**: Odoo 11 connection details (host, port, credentials, database)
- **[destination]**: Odoo 17 connection details
- **[settings]**: Logging, language, company_id

### 2. Core Modules (`app/migration/core/`)
- **odoo_connection.py**: OdooRPC connection management (singleton provider)
- **database.py**: Direct PostgreSQL access for tracking fields and lookups
- **mapping.py**: ID mapping cache (source ID → destination ID)
- **cache.py**: Generic caching service for RPC results

### 3. Handlers (`app/migration/handlers/`)
Each handler extends `DomainHandler` and implements:
- `apply_transformations(src_record)` → Returns list of transformed records
- `save_into_destination(transformed_records)` → Persists to destination

## Migration Flow

```
1. Executor selects next model from models_to_migrate
2. Fetches batch of records from source (Odoo 11) via RPC
3. For each record:
   a. Handler.apply_transformations() adapts schema
   b. Checks if record exists in destination (via x_old_id lookup)
   c. Returns {action: 'create'|'update', data: {...}, src_record, dst_record}
4. Handler.save_into_destination() for each transformed record:
   a. If action='create': dst_model.create(data)
   b. If action='update': dst_record.write(data)
   c. Updates tracking IDs in both databases
5. Repeat until EOF, then move to next model
```

## Tracking System

Two custom columns are added to tables:
- **x_new_id** (source DB): Stores the destination record ID after migration
- **x_old_id** (destination DB): Stores the source record ID

This enables:
- Idempotent migrations (re-run without duplicates)
- Foreign key resolution across migrated records
- Audit trail of migrated data

## Dependencies

- **odoorpc**: XML-RPC/JSON-RPC client for Odoo
- **psycopg2-binary**: Direct PostgreSQL access for tracking fields
