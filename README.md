# ORBITAL: SomaiyaSat & SomaiyaPod Telemetry Management System

Desktop telemetry operations console and relational data management system for the **SomaiyaSat & SomaiyaPod PocketQube mission** (AI-based inter-satellite data routing, M17 / Codec2 / SSTV / TT&C), built for the College Mini Project on **Data Management**.

---

## Tech Stack & Architecture

- **Language:** 100% Python 3.10+
- **Database:** PostgreSQL 14+ / 18 via `psycopg2-binary`
- **Data Engineering:** `pandas`, `numpy`
- **GUI:** `CustomTkinter` (Dark space theme matching Orbital web app) + `ttk.Treeview` + Animated `tk.Canvas` Starfield
- **Zero-Config Self-Bootstrapper:** `bootstrap.py` automatically checks for the database on first run, creates tables, triggers, policies, and loads the 52k dataset automatically. **No external `.sql` files are needed!**
- **Security:** `bcrypt` password hashing, 15-minute brute-force lockout, RBAC, DAC, and Bell-LaPadula MAC Row-Level Security (`RLS`)
- **Audit & Governance:** PostgreSQL Triggers (CDC `change_log`), Administrative Approval Queue (`pending_changes`), Immutable Audit Trail (`audit_events`)
- **Safe SQL Workbench:** AST validation via `sqlparse` (blocking destructive `DROP`, `TRUNCATE`, and unqualified `DELETE`/`UPDATE`), Transactional Dry-Runs (`BEGIN...ROLLBACK`)
- **Analytics & Charts:** `matplotlib` (Dark UI embedded via `FigureCanvasTkAgg`)
- **Machine Learning:** `scikit-learn` (`RandomForestClassifier` predicting packet priority)

---

## Key Modules & Capabilities

| Module | Key Capabilities |
| :--- | :--- |
| **Cosmic Starfield Login** | Animated starfield, 15-min lockout defense, quick 1-click demo credentials for 4 clearance tiers. |
| **Telemetry Records Explorer** | 52,000 UTC rows, server-side pagination, multi-filter search, sortable headers, CRUD modal dialogs, Inspector popup, CSV export. |
| **Ground Tracking Stations** | Global network of 14 amateur receiver stations with coordinates, elevation, status pills, and 1-click packet drill-down. |
| **AI Routing Intelligence** | Visual distribution of routing pathways (Direct-to-Ground, SomaiyaPod Relay, Store-and-Forward) + Scikit-Learn live priority predictor. |
| **Power & RF Dashboard** | 5 KPI Cards, 4 Matplotlib dark charts (Battery SOC Eclipse vs Sunlit, RSSI vs SNR scatter, Comm modes, Station rankings), saved anomaly queries. |
| **Safe SQL Workbench** | Interactive SQL query editor, AST safety gatekeeper (`sqlparse`), dry-run preview simulation (`BEGIN...ROLLBACK`), committed query executor. |
| **Security & Governance** | Operator account management, Pending Changes dual-approval queue, DAC grants manager, immutable Audit Trail, CDC Change Log. |

---

## Demo Operator Accounts

| Role | Username | Password | Clearance | Accessible Packets | Capabilities |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **Admin** | `admin_user` | `Admin@2026!` | **Restricted** | **52,000** | Full CRUD, user management, approval queue review, dry-run & live SQL workbench |
| **Engineer** | `flight_engineer` | `Engineer@2026!` | **Internal** | **44,872** | Read/Insert/Update telemetry, CSV export, SQL workbench, ML simulator |
| **Operator** | `station_operator` | `Operator@2026!` | **Internal** | **44,872** | Real-time monitoring, telemetry logging, queue deletion requests, CSV export |
| **Viewer** | `public_viewer` | `Viewer@2026!` | **Public** | **13,623** | Read-only access to Public downlinks (SSTV, Codec2), station network |

---

## How to Run

### 1. Launch Primary Application
```powershell
python main.py
```
*(On first run on any computer, it automatically creates the database `orbital_py_project`, sets up the tables, provisions the demo users, and loads the 52,000 dataset in seconds).*
