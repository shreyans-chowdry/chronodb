#!/usr/bin/env python3
"""
ChronoDB — Demo Data Seeder

Seeds a rich sample database (api_test.db) with:
  1. 'main' branch with 'products' and 'users' tables across multiple commits
  2. 'feature/discounts' branch with modified product discounts
  3. 'feature/inventory' branch with new items and updated stock
  4. Non-conflicting and conflicting merge scenarios ready for live demo!

Usage:
    python3 scripts/seed_demo.py
"""

import os
import sys
import time

# Ensure project root is in python path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, root_dir)

from engine.src.version.engine import VersionEngine

DB_PATH = "api_test.db"

def seed():
    print(f"📦 Seeding sample dataset into '{DB_PATH}'...")

    # Clean previous demo DB if present to start clean
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    if os.path.exists(DB_PATH + ".wal"):
        os.remove(DB_PATH + ".wal")

    engine = VersionEngine(db_path=DB_PATH)

    # ── Commit 1: Initial schema & users on main ──
    print("  [main] Commit 1: Seeding users...")
    engine.commit("main", "feat: create users table", "shreyans", changes=[
        {
            "action": "insert", "table_name": "users", "row_id": "usr_101",
            "data": {"id": "usr_101", "name": "Alice Smith", "email": "alice@company.com", "role": "admin", "status": "active"}
        },
        {
            "action": "insert", "table_name": "users", "row_id": "usr_102",
            "data": {"id": "usr_102", "name": "Bob Johnson", "email": "bob@company.com", "role": "developer", "status": "active"}
        },
        {
            "action": "insert", "table_name": "users", "row_id": "usr_103",
            "data": {"id": "usr_103", "name": "Charlie Davis", "email": "charlie@company.com", "role": "analyst", "status": "inactive"}
        }
    ])

    # ── Commit 2: Seed products table on main ──
    print("  [main] Commit 2: Seeding products table...")
    engine.commit("main", "feat: create products inventory", "shreyans", changes=[
        {
            "action": "insert", "table_name": "products", "row_id": "prod_1",
            "data": {"sku": "LAPTOP-PRO", "name": "MacBook Pro 16", "price": 2499.00, "stock": 45, "category": "Hardware"}
        },
        {
            "action": "insert", "table_name": "products", "row_id": "prod_2",
            "data": {"sku": "PHONE-ULTRA", "name": "Pixel 9 Pro", "price": 999.00, "stock": 120, "category": "Hardware"}
        },
        {
            "action": "insert", "table_name": "products", "row_id": "prod_3",
            "data": {"sku": "MONITOR-4K", "name": "Dell UltraSharp 32", "price": 749.00, "stock": 30, "category": "Peripherals"}
        }
    ])

    # ── Create branch: feature/discounts ──
    print("  [feature/discounts] Branching from main...")
    engine.branch("feature/discounts", source_branch="main")

    # Update discounts on feature/discounts
    engine.commit("feature/discounts", "feat: apply summer sale price drop", "swapnil", changes=[
        {
            "action": "update", "table_name": "products", "row_id": "prod_1",
            "data": {"sku": "LAPTOP-PRO", "name": "MacBook Pro 16", "price": 2199.00, "stock": 45, "category": "Hardware"}
        },
        {
            "action": "update", "table_name": "products", "row_id": "prod_2",
            "data": {"sku": "PHONE-ULTRA", "name": "Pixel 9 Pro", "price": 899.00, "stock": 120, "category": "Hardware"}
        }
    ])

    # ── Create branch: feature/inventory ──
    print("  [feature/inventory] Branching from main...")
    engine.branch("feature/inventory", source_branch="main")

    # Add new accessory and update stock on feature/inventory
    engine.commit("feature/inventory", "feat: restock monitors and add keyboard", "shreyans", changes=[
        {
            "action": "update", "table_name": "products", "row_id": "prod_3",
            "data": {"sku": "MONITOR-4K", "name": "Dell UltraSharp 32", "price": 749.00, "stock": 60, "category": "Peripherals"}
        },
        {
            "action": "insert", "table_name": "products", "row_id": "prod_4",
            "data": {"sku": "KEYBOARD-MECH", "name": "Keychron Q1 Max", "price": 219.00, "stock": 85, "category": "Peripherals"}
        }
    ])

    # Close engine cleanly
    engine.close()
    print("✅ Sample database seeded successfully into 'api_test.db'!")

if __name__ == "__main__":
    seed()
