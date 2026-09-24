import asyncio
from datetime import datetime, UTC
from uuid import uuid4
import asyncmy

async def reset_and_seed_admin():
    conn = await asyncmy.connect(host='127.0.0.1', port=3306, user='root', password='', db='mbga')
    now = datetime.now(UTC)
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')

    async with conn.cursor() as cur:
        # Disable foreign key checks temporarily for clean truncate
        await cur.execute("SET FOREIGN_KEY_CHECKS = 0;")
        
        tables_to_clear = [
            "login_sessions",
            "otp_challenges",
            "customer_documents",
            "customer_profiles",
            "delivery_profiles",
            "merchant_users",
            "merchants",
            "user_roles",
            "users",
            "audit_logs"
        ]
        
        for table in tables_to_clear:
            await cur.execute(f"TRUNCATE TABLE {table};")
            print(f"Cleared table: {table}")

        await cur.execute("SET FOREIGN_KEY_CHECKS = 1;")

        # Fetch super_admin role id
        await cur.execute("SELECT id FROM roles WHERE code = 'super_admin';")
        role_row = await cur.fetchone()
        if not role_row:
            print("super_admin role not found!")
            return
        super_admin_role_id = role_row[0]

        # Create fresh Super Admin user
        admin_id = str(uuid4())
        admin_mobile = "+919999999999"
        await cur.execute(
            """INSERT INTO users 
               (id, username, email, full_name, mobile_number, country_code, role, status, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);""",
            (admin_id, "superadmin", "admin@mbga.com", "Super Admin", admin_mobile, "+91", "admin", "ACTIVE", now_str, now_str)
        )

        # Assign super_admin role to this admin user
        await cur.execute(
            """INSERT INTO user_roles 
               (id, user_id, role_id, assigned_at, assigned_by, is_active, scope_type, scope_id) 
               VALUES (%s, %s, %s, %s, %s, 1, 'global', 'global');""",
            (str(uuid4()), admin_id, super_admin_role_id, now_str, admin_id)
        )

        await conn.commit()
        print(f"\n✅ Clean slate ready! Super Admin created:")
        print(f"   Mobile: 9999999999 (+919999999999)")
        print(f"   Username: superadmin")
        print(f"   User ID: {admin_id}")

    conn.close()

if __name__ == '__main__':
    asyncio.run(reset_and_seed_admin())
