"""Download official weekly menus into the standalone dashboard cache."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.menu_service import menu_service

if __name__ == "__main__":
    catalog = menu_service.refresh(force=True)
    for location_id, menu in catalog["locations"].items():
        print(json.dumps({"location": location_id, "status": menu["status"], "period": [menu.get("periodStart"), menu.get("periodEnd")], "days": len(menu["days"]), "images": len(menu["images"])}, ensure_ascii=True))
    sys.exit(0 if all(menu["status"] == "ready" for menu in catalog["locations"].values()) else 1)
