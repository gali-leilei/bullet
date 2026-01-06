"""Jinja2 template configuration."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

# Template directory
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# Initialize Jinja2 templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Add custom filters and globals if needed
templates.env.globals["app_name"] = "Bullet"

