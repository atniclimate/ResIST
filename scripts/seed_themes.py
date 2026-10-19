"""Seed themes and assign resolutions to appropriate theme categories."""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select
from src.storage.database import init_db, get_engine
from src.models.resolution import Theme, ResolutionTheme, Resolution


# 10 curated themes based on SESSION-TOPICS-PAGE.md analysis
themes_data = [
    {
        "name": "Healthcare & IHS",
        "description": "Indian Health Service funding, facilities, and medical care access",
        "icon": "healthcare"
    },
    {
        "name": "Substance Abuse Crisis",
        "description": "Opioid and fentanyl epidemic response",
        "icon": "warning"
    },
    {
        "name": "Climate & Environment",
        "description": "Climate change, EPA, environmental protection",
        "icon": "earth"
    },
    {
        "name": "Digital Infrastructure",
        "description": "Broadband, connectivity, BEAD funding",
        "icon": "broadcast"
    },
    {
        "name": "Historical Justice",
        "description": "Boarding schools, truth commissions, UN filings",
        "icon": "document"
    },
    {
        "name": "Tribal Sovereignty",
        "description": "Self-determination, P.L. 93-638, government parity",
        "icon": "shield"
    },
    {
        "name": "Education & Youth",
        "description": "Impact Aid, UNITY, youth programs",
        "icon": "graduation"
    },
    {
        "name": "Housing",
        "description": "NAHASDA, housing programs",
        "icon": "home"
    },
    {
        "name": "Criminal Justice",
        "description": "Incarceration, resentencing",
        "icon": "scale"
    },
    {
        "name": "Recognition & Awards",
        "description": "Honorary resolutions, medals",
        "icon": "trophy"
    },
]


# Theme-to-resolution assignments based on content analysis
assignments = {
    "Healthcare & IHS": ["23-45", "23-46", "23-47"],
    "Substance Abuse Crisis": ["23-48", "23-49"],
    "Climate & Environment": ["2023-40", "2023-52"],
    "Digital Infrastructure": ["2023-56", "23-55"],
    "Historical Justice": ["2023-43", "2023-44"],
    "Tribal Sovereignty": ["2023-53", "2023-54", "2023-57"],
    "Education & Youth": ["2023-42", "2023-58"],
    "Housing": ["2023-59"],
    "Criminal Justice": ["2023-51"],
    "Recognition & Awards": ["2023-41"],
}


def seed_themes():
    """Create themes and assign resolutions."""
    # Initialize database (creates tables if needed)
    init_db()
    engine = get_engine()

    with Session(engine) as session:
        # Create themes (skip if already exists)
        theme_map = {}  # name -> Theme object
        for theme_data in themes_data:
            existing = session.exec(
                select(Theme).where(Theme.name == theme_data["name"])
            ).first()

            if existing:
                print(f"Theme '{theme_data['name']}' already exists, skipping")
                theme_map[theme_data["name"]] = existing
            else:
                theme = Theme(**theme_data)
                session.add(theme)
                session.flush()  # Get ID
                theme_map[theme_data["name"]] = theme
                print(f"Created theme: {theme_data['name']}")

        session.commit()

        # Assign resolutions to themes
        links_created = 0
        links_skipped = 0
        resolutions_not_found = []

        for theme_name, resolution_numbers in assignments.items():
            theme = theme_map[theme_name]

            for res_num in resolution_numbers:
                # Find resolution by resolution_number
                resolution = session.exec(
                    select(Resolution).where(Resolution.resolution_number == res_num)
                ).first()

                if not resolution:
                    resolutions_not_found.append(res_num)
                    continue

                # Check if link already exists
                existing_link = session.exec(
                    select(ResolutionTheme).where(
                        ResolutionTheme.resolution_id == resolution.id,
                        ResolutionTheme.theme_id == theme.id
                    )
                ).first()

                if existing_link:
                    links_skipped += 1
                    continue

                # Create link
                link = ResolutionTheme(resolution_id=resolution.id, theme_id=theme.id)
                session.add(link)
                links_created += 1

        session.commit()

        print(f"\nSeeding complete:")
        print(f"  Themes: {len(themes_data)}")
        print(f"  Links created: {links_created}")
        print(f"  Links skipped (existing): {links_skipped}")

        if resolutions_not_found:
            print(f"\nWarning: Resolution numbers not found in database:")
            for res_num in resolutions_not_found:
                print(f"  - {res_num}")


if __name__ == "__main__":
    seed_themes()
