"""
Restaurant Discovery Agent for Lunchdejt.
Orchestrates finding, researching, testing, validating, and staging new lunch restaurant candidates.
"""
import os
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from engine.pipeline import scrape_restaurant
from engine.validator import validate_menu_result
from engine.fetcher import fetch_html

from .models import RestaurantCandidate, DiscoveryStatus, slugify
from .finder import find_restaurants
from .researcher import research_candidate
from .strategy import detect_strategy

logger = logging.getLogger("discovery_agent")

class RestaurantDiscoveryAgent:
    def __init__(
        self,
        candidates_file: str = "config/candidates.json",
        restaurants_file: str = "config/restaurants.json"
    ):
        self.candidates_file = candidates_file
        self.restaurants_file = restaurants_file
        self.existing_ids = self._load_existing_restaurant_ids()
        self.candidates: Dict[str, RestaurantCandidate] = self._load_existing_candidates()

    def _load_existing_restaurant_ids(self) -> List[str]:
        """Loads IDs of restaurants already in production config to avoid duplicates."""
        if not os.path.exists(self.restaurants_file) or os.path.getsize(self.restaurants_file) == 0:
            return []
        try:
            with open(self.restaurants_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [r.get("id") for r in data if r.get("id")]
        except Exception as e:
            logger.warning(f"Failed to load existing restaurants: {e}")
            return []

    def _load_existing_candidates(self) -> Dict[str, RestaurantCandidate]:
        """Loads previously saved candidates if available."""
        if not os.path.exists(self.candidates_file) or os.path.getsize(self.candidates_file) == 0:
            return {}
        try:
            with open(self.candidates_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                result = {}
                for item in data:
                    c = RestaurantCandidate.from_dict(item)
                    result[c.id] = c
                return result
        except Exception as e:
            logger.warning(f"Failed to load candidates file: {e}")
            return {}

    def discover(self, city: str = "Göteborg", limit: int = 20) -> List[RestaurantCandidate]:
        """
        Phase 1: Finds new restaurants in the target city that are not already active in Lunchdejt.
        """
        raw_list = find_restaurants(city=city, limit=limit, existing_ids=self.existing_ids)
        new_candidates = []

        for item in raw_list:
            cid = slugify(item["name"])
            if cid in self.candidates:
                new_candidates.append(self.candidates[cid])
            else:
                c = RestaurantCandidate(
                    id=cid,
                    name=item["name"],
                    city=item.get("city", city),
                    address=item.get("address"),
                    website=item.get("website"),
                    status=DiscoveryStatus.DISCOVERED
                )
                self.candidates[c.id] = c
                new_candidates.append(c)

        return new_candidates[:limit]

    def research(self, candidate: RestaurantCandidate) -> RestaurantCandidate:
        """
        Phase 2: Researches the candidate's website to find lunch menu sources.
        """
        candidate = research_candidate(candidate)
        
        # Determine strategy if lunch was found
        if candidate.lunch_found and candidate.lunch_url:
            html = None
            if not candidate.lunch_url.lower().endswith('.pdf'):
                html, _ = fetch_html(candidate.lunch_url)
            candidate.strategy = detect_strategy(html, candidate.lunch_url)
        
        candidate.updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.candidates[candidate.id] = candidate
        return candidate

    def test_scraper(self, candidate: RestaurantCandidate) -> RestaurantCandidate:
        """
        Phase 3: Tests candidate scraping against the existing Lunchdejt engine pipeline.
        Runs validation and records results without touching production data.
        """
        if not candidate.lunch_url and not candidate.website:
            candidate.status = DiscoveryStatus.FAILED
            candidate.error = "No URL available for testing"
            return candidate

        candidate_cfg = candidate.to_restaurant_config()
        
        # Run through the core engine pipeline
        menu_result = scrape_restaurant(candidate_cfg)
        
        # Validate result
        is_valid, issues = validate_menu_result(menu_result)
        candidate.validation_issues = issues

        total_dishes = sum(len(d.dishes) for d in menu_result.days) if menu_result.days else 0
        total_days = len(menu_result.days) if menu_result.days else 0

        candidate.test_result = {
            "success": menu_result.success,
            "source": menu_result.source,
            "error": menu_result.error,
            "days_found": total_days,
            "dishes_found": total_dishes,
            "is_valid": is_valid,
            "preview": menu_result.formatted_menu[:300] if menu_result.formatted_menu else ""
        }

        if is_valid and menu_result.success and total_dishes > 0:
            candidate.status = DiscoveryStatus.PENDING_APPROVAL
            candidate.error = None
        elif menu_result.formatted_menu and len(menu_result.formatted_menu) > 30:
            # Menu found but format slightly non-standard -> flag for human review
            candidate.status = DiscoveryStatus.NEEDS_MANUAL_REVIEW
            candidate.error = "; ".join(issues) if issues else "Needs format review"
        else:
            candidate.status = DiscoveryStatus.FAILED
            candidate.error = menu_result.error or "; ".join(issues) or "Scrape produced no valid menu"

        candidate.updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.candidates[candidate.id] = candidate
        return candidate

    def save_candidates(self, filepath: Optional[str] = None):
        """Persists candidates to JSON."""
        target_path = filepath or self.candidates_file
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        data = [c.to_dict() for c in self.candidates.values()]
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(data)} candidates to {target_path}")

    def run_pipeline(
        self,
        city: str = "Göteborg",
        limit: int = 20,
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """
        Executes the end-to-end discovery flow:
        Find -> Research -> Test Scraper -> Validate -> Stage Candidates.
        """
        logger.info(f"Starting Restaurant Discovery Agent for {city} (limit: {limit})...")
        
        # 1. Discover
        discovered = self.discover(city=city, limit=limit)
        
        researched_count = 0
        lunch_confirmed_count = 0
        tested_count = 0
        approved_ready_count = 0

        # 2. Research & Test
        for cand in discovered:
            self.research(cand)
            researched_count += 1
            
            if cand.lunch_found:
                lunch_confirmed_count += 1
                self.test_scraper(cand)
                tested_count += 1
                if cand.status == DiscoveryStatus.PENDING_APPROVAL:
                    approved_ready_count += 1

        # 3. Save to candidates file
        self.save_candidates()

        summary = {
            "city": city,
            "total_discovered": len(discovered),
            "researched": researched_count,
            "lunch_confirmed": lunch_confirmed_count,
            "scrapers_tested": tested_count,
            "pending_approval": approved_ready_count,
            "dry_run": dry_run,
            "candidates_file": self.candidates_file,
            "candidates": [c.to_dict() for c in discovered]
        }
        return summary

    def approve_candidate(self, candidate_id: str) -> bool:
        """
        Human Approval Workflow:
        Safely transfers an approved candidate into production config/restaurants.json.
        Ensures existing restaurants are never broken.
        """
        if candidate_id not in self.candidates:
            return False

        candidate = self.candidates[candidate_id]
        new_config = candidate.to_restaurant_config()

        # Load existing restaurants
        with open(self.restaurants_file, "r", encoding="utf-8") as f:
            active_list = json.load(f)

        # Check if already present
        for item in active_list:
            if item.get("id") == candidate_id:
                # Update existing
                item.update(new_config)
                break
        else:
            # Append new
            active_list.append(new_config)

        # Save back to production config
        with open(self.restaurants_file, "w", encoding="utf-8") as f:
            json.dump(active_list, f, ensure_ascii=False, indent=2)

        candidate.status = DiscoveryStatus.APPROVED
        candidate.updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.save_candidates()
        return True
