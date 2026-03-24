"""
Generates the weekly HTML report from a list of new leads.
"""
import logging
import os
from datetime import datetime
from typing import List

from jinja2 import Environment, FileSystemLoader

import config

logger = logging.getLogger(__name__)


def generate_report(new_leads: List[dict], report_date: str = "") -> str:
    """
    Render the HTML report template with the given leads.
    Returns the rendered HTML string.
    Also saves the report as a file in data/reports/.
    """
    if not report_date:
        report_date = datetime.now().strftime("%B %d, %Y")

    # Group leads by type
    leads_by_type = {
        config.LEAD_TYPE_PROBATE: [],
        config.LEAD_TYPE_FORECLOSURE: [],
        config.LEAD_TYPE_TAX_DEFAULT: [],
        config.LEAD_TYPE_DIVORCE: [],
    }
    for lead in new_leads:
        lt = lead.get("lead_type", "")
        if lt in leads_by_type:
            leads_by_type[lt].append(lead)

    counts = {k: len(v) for k, v in leads_by_type.items()}
    total_new = len(new_leads)

    # Render template
    env = Environment(loader=FileSystemLoader(config.TEMPLATE_DIR))
    template = env.get_template("report.html")

    html = template.render(
        report_date=report_date,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        total_new=total_new,
        counts=counts,
        leads_by_type=leads_by_type,
    )

    # Save to file
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    filename = datetime.now().strftime("report_%Y-%m-%d.html")
    filepath = os.path.join(config.REPORTS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Report saved to %s", filepath)
    return html
