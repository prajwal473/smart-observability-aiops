from app.db.database import SessionLocal
from app.models import Tenant, Collector

db = SessionLocal()

try:
    tenant = db.get(Tenant, "tenant-001")

    if tenant is None:
        tenant = Tenant(
            tenant_id="tenant-001",
            name="Demo Organization",
        )
        db.add(tenant)

    collector = db.get(Collector, "collector-001")

    if collector is None:
        collector = Collector(
            collector_id="collector-001",
            tenant_id="tenant-001",
            collector_version="1.0.0",
            config_status="healthy",
        )
        db.add(collector)

    db.commit()

    print("Test tenant and collector created successfully!")

except Exception:
    db.rollback()
    raise

finally:
    db.close()