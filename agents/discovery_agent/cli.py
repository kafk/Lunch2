"""
CLI runner for the Restaurant Discovery Agent.
"""
import argparse
import sys
import os

# Add Lunch2 root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents.discovery_agent.agent import RestaurantDiscoveryAgent
from agents.discovery_agent.models import DiscoveryStatus

def main():
    parser = argparse.ArgumentParser(description="Lunchdejt Restaurant Discovery Agent")
    parser.add_argument("--city", default="Göteborg", help="Target city")
    parser.add_argument("--limit", type=int, default=20, help="Number of restaurants to discover")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Run without activating into production")
    parser.add_argument("--approve", type=str, default=None, help="Approve candidate ID into production config")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    agent = RestaurantDiscoveryAgent()

    if args.approve:
        print(f"Approving candidate: {args.approve}...")
        success = agent.approve_candidate(args.approve)
        if success:
            print(f"✓ Candidate {args.approve} approved and added to production config!")
        else:
            print(f"✗ Failed to approve {args.approve}")
        return

    print("=" * 60)
    print(f"  LUNCHDEJT - RESTAURANT DISCOVERY AGENT")
    print(f"  Mål: {args.city} | Begränsning: {args.limit} restauranger")
    print("=" * 60)

    summary = agent.run_pipeline(city=args.city, limit=args.limit, dry_run=args.dry_run)

    print("\n--- RESULTAT ---")
    print(f"  Upptäckta restauranger: {summary['total_discovered']}")
    print(f"  Undersökta webbplatser: {summary['researched']}")
    print(f"  Lunch bekräftad:        {summary['lunch_confirmed']}")
    print(f"  Testskrapade:           {summary['scrapers_tested']}")
    print(f"  Redo för godkännande:   {summary['pending_approval']}")
    print(f"  Kandidatfil:            {summary['candidates_file']}")
    print("-" * 60)

    for cand in summary["candidates"]:
        status = cand.get("status")
        name = cand.get("name")
        lunch_url = cand.get("lunch_url") or cand.get("website")
        test = cand.get("test_result") or {}
        dishes = test.get("dishes_found", 0)

        mark = "[?]"
        if status == DiscoveryStatus.PENDING_APPROVAL.value:
            mark = "[OK]"
        elif status == DiscoveryStatus.NEEDS_MANUAL_REVIEW.value:
            mark = "[WARN]"
        elif status == DiscoveryStatus.FAILED.value:
            mark = "[FAIL]"

        print(f" {mark:<7} {name:<25} [{status:<18}] Rätter: {dishes:<2} URL: {lunch_url}")

    print("=" * 60)
    print("Kandidater sparade till config/candidates.json.")
    print("Inga produktionsrestauranger i config/restaurants.json har ändrats.")

if __name__ == "__main__":
    main()
