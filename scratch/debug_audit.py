import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

# Mock OPERATOR_PACK_DIR if needed
# os.environ["FLOW_OPERATOR_PACK_DIR"] = r"C:\Users\USER\Desktop\The Real Avengers Bosmax - Copy"

from agent.services.fastmoss_taxonomy_reconciliation_service import FastMossTaxonomyReconciliationService

async def main():
    try:
        print("Starting full FastMoss audit...")
        report = await FastMossTaxonomyReconciliationService.perform_full_fastmoss_audit(limit=1)
        print("Audit successful!")
        print(f"Total FastMoss: {report.get('total_fastmoss_products')}")
        print(f"Contaminated count: {report.get('contaminated_or_keyword_derived_count')}")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
