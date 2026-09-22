"""
Data models and interfaces for Lunch2 scraping pipeline.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime

@dataclass
class MenuItem:
    dish: str
    description: Optional[str] = None
    price: Optional[int] = None
    category: Optional[str] = None  # t.ex. 'Kött', 'Fisk', 'Veg', 'Pasta'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dish": self.dish,
            "description": self.description,
            "price": self.price,
            "category": self.category
        }

@dataclass
class DayMenu:
    day: str  # 'Måndag', 'Tisdag', etc.
    dishes: List[MenuItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "day": self.day,
            "dishes": [d.to_dict() for d in self.dishes]
        }

@dataclass
class WeeklyMenuResult:
    restaurant_id: str
    name: str
    url: str
    success: bool
    source: str
    raw_text: str = ""
    formatted_menu: str = ""
    days: List[DayMenu] = field(default_factory=list)
    error: Optional[str] = None
    scraped_at: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M'))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "restaurant_id": self.restaurant_id,
            "name": self.name,
            "url": self.url,
            "success": self.success,
            "source": self.source,
            "menu": self.formatted_menu,
            "raw_text": self.raw_text,
            "days": [d.to_dict() for d in self.days],
            "error": self.error,
            "scraped_at": self.scraped_at
        }
