import logging
import datetime
from sqlalchemy import select
from database.session import async_session
from database.models import Casting, ActorProfile, Match

logger = logging.getLogger(__name__)

async def match_casting_with_actors(casting_id: int) -> None:
    logger.info(f"Triggered matcher for casting_id={casting_id}")

    async with async_session() as session:
        result = await session.execute(select(Casting).where(Casting.id == casting_id))
        casting = result.scalar_one_or_none()
        if not casting:
            logger.error(f"Casting id={casting_id} not found.")
            return

        import json
        criteria = json.loads(casting.criteria) if isinstance(casting.criteria, str) else (casting.criteria or {})

        c_genders       = criteria.get("genders", [])
        c_age_min       = criteria.get("age_min", 0)
        c_age_max       = criteria.get("age_max", 100)
        c_cities        = criteria.get("cities", [])
        c_project_types = criteria.get("project_types", [])
        c_fee           = criteria.get("fee", 0) or 0
        c_is_ams        = criteria.get("is_ams", False)

        # Base query — only actors with active subscription
        actors_stmt = select(ActorProfile).where(
            ActorProfile.subscription_end_date > datetime.datetime.now()
        )

        # Gender filter
        if c_genders:
            actors_stmt = actors_stmt.where(ActorProfile.gender.in_(c_genders))

        actors = (await session.execute(actors_stmt)).scalars().all()

        matched_actors = []
        for actor in actors:
            reasons = []

            # Fee — если актёр указал min_fee, то в кастинге ОБЯЗАТЕЛЬНО должен быть fee и он должен покрывать
            actor_min_fee = actor.min_fee or 0
            if actor_min_fee > 0:
                if c_fee == 0:
                    reasons.append(f"fee: casting has no fee, actor wants min {actor_min_fee}")
                elif c_fee < actor_min_fee:
                    reasons.append(f"fee (actor min {actor_min_fee} > casting fee {c_fee})")

            # Age range must overlap
            # Если актёр указал возраст — кастинг должен его покрывать
            if actor.playing_age_min > 0 or actor.playing_age_max < 100:
                if actor.playing_age_min > c_age_max or actor.playing_age_max < c_age_min:
                    reasons.append(f"age (actor {actor.playing_age_min}-{actor.playing_age_max} vs casting {c_age_min}-{c_age_max})")

            # City filter
            # Если актёр указал конкретные города (не "Все города")
            if c_cities:
                actor_cities = [c.strip() for c in (actor.city or "").split(",")]
                if "Все города" not in actor_cities:
                    if not any(city in actor_cities for city in c_cities) and "Все города" not in c_cities:
                        reasons.append(f"city (actor {actor_cities} vs casting {c_cities})")

            # --- Project type filter ---
            proj_map = {
                "Кино и сериалы": actor.proj_cinema,
                "Реклама": actor.proj_ads,
                "Некоммерч": actor.proj_nonprofit,
                "Международные": actor.proj_international,
                "Клипы": actor.proj_clips,
                "Театр": actor.proj_theater,
                "Озвучка": actor.proj_dubbing,
                "Другое": actor.proj_other,
            }

            if c_project_types:
                actor_enabled_types = [k for k, v in proj_map.items() if v]
                if actor_enabled_types:
                    has_project_match = any(
                        pt in actor_enabled_types or actor_enabled_type in pt
                        for pt in c_project_types
                        for actor_enabled_type in actor_enabled_types
                    )
                    if not has_project_match:
                        reasons.append(f"project (actor {actor_enabled_types} vs casting {c_project_types})")

            # AMS option
            if c_is_ams and actor.opt_exclude_ams:
                reasons.append("ams excluded")

            # Все проверки должны пройти (AND — совокупность)
            if reasons:
                logger.info(f"Actor {actor.user_id} ({actor.full_name}) SKIPPED: {'; '.join(reasons)}")
                continue

            matched_actors.append(actor)

        if not matched_actors:
            logger.info(f"No matching actors for casting_id={casting_id}")
            return

        new_matches = []
        for actor in matched_actors:
            match = Match(actor_id=actor.user_id, casting_id=casting_id, status="pending")
            new_matches.append(match)
        session.add_all(new_matches)
        await session.commit()
        logger.info(f"Created {len(new_matches)} matches for casting_id={casting_id}")

        from .notifier import notify_matched_actors
        await notify_matched_actors(casting_id)
