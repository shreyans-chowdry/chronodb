#!/usr/bin/env python3
"""
ChronoDB — Interview Showcase Data Seeder

Seeds a rich, realistic enterprise database (api_test.db) with:
  1. 'main' branch (Production):
     - 'users' table: Enterprise team directory (Alice, Bob, Charlie, Diana, Evan)
     - 'products' table: Enterprise hardware catalog (MacBook, Dell 4K, Keychron, Sony ANC, Server)
     - 'orders' table: High-value transaction ledger
  2. 'develop' branch (Staging):
     - Restocked inventory and pricing updates
     - New enterprise hardware (Apple Studio Display)
     - Onboarded DevOps/SecOps personnel
  3. 'feature/discounts-promo' branch (Ready for Live Diff & Merge Demo):
     - Q4 promotional hardware price drops
     - Perfect for demonstrating side-by-side cell-level diff and clean 3-way merge in interviews!
  4. 'feature/audit-compliance' branch:
     - Compliance-flagged transactions for compliance/auditing use cases
     - Demonstrates branch isolation and commit DAG topology

Usage:
    python3 scripts/seed_demo.py
"""

import os
import sys

# Ensure project root is in python path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, root_dir)

from engine.src.version.engine import VersionEngine

DB_PATH = "api_test.db"

def seed():
    print(f"📦 Seeding interview-ready showcase dataset into '{DB_PATH}'...")

    # Clean previous demo DB if present to start completely fresh
    for ext in ["", ".wal", ".lock"]:
        path = DB_PATH + ext
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    engine = VersionEngine(db_path=DB_PATH)

    # ══════════════════════════════════════════════════════════════
    # 1. MAIN BRANCH — PRODUCTION BASELINE
    # ══════════════════════════════════════════════════════════════

    # ── Commit 1: Enterprise Users ──
    print("  [main] Commit 1: Seeding enterprise staff directory...")
    engine.commit(
        branch_name="main",
        message="feat: initialize enterprise schema & seed corporate directory",
        author="shreyans",
        changes=[
            {
                "action": "insert", "table_name": "users", "row_id": "usr_101",
                "data": {
                    "name": "Alice Smith",
                    "email": "alice.smith@techcorp.internal",
                    "role": "VP Engineering",
                    "department": "Engineering",
                    "status": "Active"
                }
            },
            {
                "action": "insert", "table_name": "users", "row_id": "usr_102",
                "data": {
                    "name": "Bob Johnson",
                    "email": "bob.johnson@techcorp.internal",
                    "role": "Lead Systems Architect",
                    "department": "Infrastructure",
                    "status": "Active"
                }
            },
            {
                "action": "insert", "table_name": "users", "row_id": "usr_103",
                "data": {
                    "name": "Charlie Davis",
                    "email": "charlie.davis@techcorp.internal",
                    "role": "Staff Data Scientist",
                    "department": "AI & Analytics",
                    "status": "Active"
                }
            },
            {
                "action": "insert", "table_name": "users", "row_id": "usr_104",
                "data": {
                    "name": "Diana Prince",
                    "email": "diana.prince@techcorp.internal",
                    "role": "Chief Information Security Officer",
                    "department": "Security",
                    "status": "Active"
                }
            },
            {
                "action": "insert", "table_name": "users", "row_id": "usr_105",
                "data": {
                    "name": "Evan Wright",
                    "email": "evan.wright@techcorp.internal",
                    "role": "Director of Product",
                    "department": "Product Management",
                    "status": "Active"
                }
            }
        ]
    )

    # ── Commit 2: Enterprise Products Catalog ──
    print("  [main] Commit 2: Seeding hardware & peripherals catalog...")
    engine.commit(
        branch_name="main",
        message="feat: catalog enterprise hardware & peripherals inventory",
        author="shreyans",
        changes=[
            {
                "action": "insert", "table_name": "products", "row_id": "prod_1",
                "data": {
                    "sku": "HW-MBP-M3",
                    "title": "MacBook Pro 16 M3 Max",
                    "category": "Hardware",
                    "unit_price": "3499.00",
                    "stock_qty": "42",
                    "status": "In Stock"
                }
            },
            {
                "action": "insert", "table_name": "products", "row_id": "prod_2",
                "data": {
                    "sku": "PER-DELL-32",
                    "title": "Dell UltraSharp 32 4K USB-C Hub",
                    "category": "Peripherals",
                    "unit_price": "899.00",
                    "stock_qty": "65",
                    "status": "In Stock"
                }
            },
            {
                "action": "insert", "table_name": "products", "row_id": "prod_3",
                "data": {
                    "sku": "PER-KEY-Q1",
                    "title": "Keychron Q1 Pro Wireless Mechanical",
                    "category": "Peripherals",
                    "unit_price": "219.00",
                    "stock_qty": "110",
                    "status": "In Stock"
                }
            },
            {
                "action": "insert", "table_name": "products", "row_id": "prod_4",
                "data": {
                    "sku": "AUD-SONY-XM5",
                    "title": "Sony WH-1000XM5 Wireless ANC",
                    "category": "Audio",
                    "unit_price": "399.00",
                    "stock_qty": "85",
                    "status": "In Stock"
                }
            },
            {
                "action": "insert", "table_name": "products", "row_id": "prod_5",
                "data": {
                    "sku": "SRV-SYS-2U",
                    "title": "Supermicro 2U Dual Xeon Cloud Node",
                    "category": "Infrastructure",
                    "unit_price": "6450.00",
                    "stock_qty": "14",
                    "status": "Low Stock"
                }
            }
        ]
    )

    # ── Commit 3: Enterprise Orders Ledger ──
    print("  [main] Commit 3: Seeding initial enterprise purchase ledger...")
    engine.commit(
        branch_name="main",
        message="feat: record initial enterprise purchase transactions",
        author="swapnil",
        changes=[
            {
                "action": "insert", "table_name": "orders", "row_id": "ord_801",
                "data": {
                    "customer": "Alice Smith",
                    "sku": "HW-MBP-M3",
                    "quantity": "2",
                    "total_amount": "6998.00",
                    "payment_status": "Settled",
                    "region": "US-West"
                }
            },
            {
                "action": "insert", "table_name": "orders", "row_id": "ord_802",
                "data": {
                    "customer": "Bob Johnson",
                    "sku": "SRV-SYS-2U",
                    "quantity": "1",
                    "total_amount": "6450.00",
                    "payment_status": "Settled",
                    "region": "US-East"
                }
            },
            {
                "action": "insert", "table_name": "orders", "row_id": "ord_803",
                "data": {
                    "customer": "Diana Prince",
                    "sku": "AUD-SONY-XM5",
                    "quantity": "5",
                    "total_amount": "1995.00",
                    "payment_status": "Processing",
                    "region": "EU-Central"
                }
            }
        ]
    )

    # ══════════════════════════════════════════════════════════════
    # 2. DEVELOP BRANCH — STAGING ENVIRONMENT
    # ══════════════════════════════════════════════════════════════
    print("  [develop] Creating staging branch from main...")
    engine.branch("develop", source_branch="main", pull_from_main=True)

    # Commit on develop: Restock and add product
    print("  [develop] Commit: Restocking monitors, discounting servers & adding Studio Display...")
    engine.commit(
        branch_name="develop",
        message="feat: restock peripherals & adjust enterprise server pricing",
        author="shreyans",
        changes=[
            {
                "action": "update", "table_name": "products", "row_id": "prod_2",
                "data": {
                    "sku": "PER-DELL-32",
                    "title": "Dell UltraSharp 32 4K USB-C Hub",
                    "category": "Peripherals",
                    "unit_price": "899.00",
                    "stock_qty": "120",
                    "status": "In Stock"
                }
            },
            {
                "action": "update", "table_name": "products", "row_id": "prod_5",
                "data": {
                    "sku": "SRV-SYS-2U",
                    "title": "Supermicro 2U Dual Xeon Cloud Node",
                    "category": "Infrastructure",
                    "unit_price": "5999.00",
                    "stock_qty": "20",
                    "status": "In Stock"
                }
            },
            {
                "action": "insert", "table_name": "products", "row_id": "prod_6",
                "data": {
                    "sku": "PER-APL-DISP",
                    "title": "Apple Studio Display 27 5K Retina",
                    "category": "Peripherals",
                    "unit_price": "1599.00",
                    "stock_qty": "35",
                    "status": "In Stock"
                }
            }
        ]
    )

    # Another commit on develop: New staff member
    print("  [develop] Commit: Onboarding SecOps engineer...")
    engine.commit(
        branch_name="develop",
        message="feat: onboard senior security operations lead Frank Miller",
        author="swapnil",
        changes=[
            {
                "action": "insert", "table_name": "users", "row_id": "usr_106",
                "data": {
                    "name": "Frank Miller",
                    "email": "frank.miller@techcorp.internal",
                    "role": "Lead Security Operations Engineer",
                    "department": "Security",
                    "status": "Active"
                }
            }
        ]
    )

    # ══════════════════════════════════════════════════════════════
    # 3. FEATURE/DISCOUNTS-PROMO — READY FOR LIVE DIFF & MERGE DEMO
    # ══════════════════════════════════════════════════════════════
    print("  [feature/discounts-promo] Creating promo campaign branch from main...")
    engine.branch("feature/discounts-promo", source_branch="main", pull_from_main=True)

    print("  [feature/discounts-promo] Commit: Applying promotional pricing...")
    engine.commit(
        branch_name="feature/discounts-promo",
        message="feat: apply Q4 enterprise hardware promotional discounts (-15%)",
        author="swapnil",
        changes=[
            {
                "action": "update", "table_name": "products", "row_id": "prod_1",
                "data": {
                    "sku": "HW-MBP-M3",
                    "title": "MacBook Pro 16 M3 Max",
                    "category": "Hardware",
                    "unit_price": "2999.00",
                    "stock_qty": "42",
                    "status": "Promo Price"
                }
            },
            {
                "action": "update", "table_name": "products", "row_id": "prod_4",
                "data": {
                    "sku": "AUD-SONY-XM5",
                    "title": "Sony WH-1000XM5 Wireless ANC",
                    "category": "Audio",
                    "unit_price": "349.00",
                    "stock_qty": "85",
                    "status": "Promo Price"
                }
            },
            {
                "action": "insert", "table_name": "products", "row_id": "prod_7",
                "data": {
                    "sku": "PER-TS4-DOCK",
                    "title": "CalDigit TS4 Thunderbolt 4 Dock 18-Port",
                    "category": "Peripherals",
                    "unit_price": "379.00",
                    "stock_qty": "75",
                    "status": "In Stock"
                }
            }
        ]
    )

    # ══════════════════════════════════════════════════════════════
    # 4. FEATURE/AUDIT-COMPLIANCE — COMPLIANCE TRACKING & DAG TOPOLOGY
    # ══════════════════════════════════════════════════════════════
    print("  [feature/audit-compliance] Creating compliance branch from develop...")
    engine.branch("feature/audit-compliance", source_branch="develop", pull_from_main=True)

    print("  [feature/audit-compliance] Commit: Flagging high-value transaction for compliance...")
    engine.commit(
        branch_name="feature/audit-compliance",
        message="feat: audit high-value European cross-border transaction for SOX compliance",
        author="shreyans",
        changes=[
            {
                "action": "insert", "table_name": "orders", "row_id": "ord_804",
                "data": {
                    "customer": "Frank Miller",
                    "sku": "SRV-SYS-2U",
                    "quantity": "2",
                    "total_amount": "11998.00",
                    "payment_status": "Audit Pending",
                    "region": "EU-Central"
                }
            }
        ]
    )

    # Close engine cleanly
    engine.close()
    print("✅ Interview showcase database successfully generated in 'api_test.db'!")

if __name__ == "__main__":
    seed()
