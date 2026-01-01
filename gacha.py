from tools import get_reference, set_reference, debug_print, get_app_root
from db import get_setting
from gacha_overlay_bridge import GachaOverlayBridge
from pathlib import Path
from random import randint, random, choice
from typing import Literal, Any, Optional

class Gacha():
    def __init__(self):
        set_reference("GachaHandler", self)
        self.online_database = get_reference("OnlineDatabase")
        self.online_storage = get_reference("OnlineStorage")
        self.twitch_bot = get_reference("TwitchBot")
        self.overlay_bridge: Optional[GachaOverlayBridge] = get_reference("GachaOverlay")
        self._overlay_config: dict[str, Any] = {}
        self.ur_chance = 0.35
        self.ssr_chance = 1.75
        self.sr_chance = 7.9
        self.r_chance = 25.0
        self.local_gacha_path = Path(get_app_root()) / "media" / "gacha" / "sets"
        self.current_sets = []
        self.rarity_map = {
            "UR": "legendary",
            "SSR": "epic",
            "SR": "rare",
            "R": "uncommon",
            "N": "common"
        }
        pass  # Placeholder for Gacha class

    async def startup(self):
        """Checks local_gacha_path for existence and creates it if missing. Also checks if all gacha names exist in the online database. If not,
        adds them to the database using the set name derived from the folder structure, the rarity derived from the parent folder name, the name
        from the file name without extension. Then uploads the image after renaming it to the unique id of the gacha with extension to the storage 
        and adds the url to the image to the entry for that database.
        Skips folder called 'animations'."""
        if not self.online_database:
            self.online_database = get_reference("OnlineDatabase")
        if not self.online_storage:
            self.online_storage = get_reference("OnlineStorage")
        await self._ensure_overlay_bridge()
        online_gacha_list = await self.online_database.get_all_gacha_data()
        online_gacha_names = {gacha["name"].lower() for gacha in online_gacha_list}
        if not self.local_gacha_path.exists():
            self.local_gacha_path.mkdir(parents=True, exist_ok=True)
            debug_print("Gacha", f"Created missing gacha sets directory at {self.local_gacha_path}.")
            return
        
        local_shinies = []
        new_gachas = []
        debug_print("Gacha", f"Scanning local gacha sets directory at {self.local_gacha_path} for gacha files.")
        for set_folder in self.local_gacha_path.iterdir():
            debug_print("Gacha", f"Processing set folder: {set_folder.name}")
            if set_folder.is_dir():
                set_name = set_folder.name.lower()
                for rarity_folder in set_folder.iterdir():
                    if rarity_folder.is_dir():
                        rarity = rarity_folder.name.lower() #should be one of "common", "uncommon", "rare", "epic", "legendary"
                        if rarity in self.rarity_map.values():
                            rarity = [key for key, value in self.rarity_map.items() if value == rarity][0]  #convert back to "N", "R", "SR", "SSR", "UR"
                        else:
                            debug_print("Gacha", f"Skipping unknown rarity folder '{rarity_folder.name}' in set '{set_name}'.")
                            continue
                        for gacha_file in rarity_folder.iterdir():
                            if gacha_file.is_file():
                                gacha_name = gacha_file.stem.lower()
                                if gacha_name not in online_gacha_names:
                                    debug_print("Gacha", f"Adding missing gacha '{gacha_name}' from set '{set_name}' with rarity '{rarity}' to online database.")
                                    await self.online_database.create_gacha_entry(name=gacha_name, set_name=set_name, rarity=rarity, local_image_path=str(gacha_file))
                                    online_gacha_names.add(gacha_name)
                                    new_gachas.append(gacha_name)
                            elif gacha_file.is_dir():
                                for subfile in gacha_file.iterdir():
                                    if subfile.is_file():
                                        gacha_name = subfile.stem.lower()
                                        local_shinies.append((gacha_name, set_name, subfile))
        new_shinies = []
        if local_shinies:
            debug_print("Gacha", f"Processing {len(local_shinies)} shiny gacha files.")
            for gacha_name, set_name, shiny_file in local_shinies:
                for gacha in online_gacha_list:
                    if gacha["name"].lower() == gacha_name and gacha["set_name"].lower() == set_name:
                        gacha_data = gacha
                        break
                if gacha_data:
                    if gacha_data["shiny_image_path"] in [None, ""]:
                        debug_print("Gacha", f"Adding shiny image for gacha '{gacha_name}' in set '{set_name}' to online database.")
                        await self.online_database.update_shiny_gacha_data(
                            gacha_id=gacha_data["id"],
                            set_name=set_name,
                            local_shiny_image_path=str(shiny_file),
                        )
                else:
                    debug_print("Gacha", f"Shiny gacha '{gacha_name}' in set '{set_name}' has no matching normal gacha entry. Skipping shiny addition.")
        debug_print("Gacha", f"Found {len(new_gachas)} new gachas. Added {len(new_shinies)} new shinies.")

    async def check_for_new_gacha(self) -> list[str]:
        """Called from a button on the GUI to check for new gacha files added to the local gacha folder, 
        then adds them to the online database and uploads the images to storage."""
        debug_print("Gacha", "Checking for new gacha files in local gacha directory.")
        local_shinies = []
        if not self.online_database:
            self.online_database = get_reference("OnlineDatabase")
        if not self.online_storage:
            self.online_storage = get_reference("OnlineStorage")
        online_gacha_list = await self.online_database.get_all_gacha_data()
        online_gacha_names = {gacha["name"].lower() for gacha in online_gacha_list}
        new_gachas = []
        for set_folder in self.local_gacha_path.iterdir():
            if set_folder.is_dir():
                set_name = set_folder.name.lower()
                for rarity_folder in set_folder.iterdir():
                    if rarity_folder.is_dir():
                        rarity = rarity_folder.name.lower() #should be one of "common", "uncommon", "rare", "epic", "legendary"
                        if rarity in self.rarity_map.values():
                            rarity = [key for key, value in self.rarity_map.items() if value == rarity][0]  #convert back to "N", "R", "SR", "SSR", "UR"
                        else:
                            continue
                        for gacha_file in rarity_folder.iterdir():
                            if gacha_file.is_file():
                                gacha_name = gacha_file.stem.lower()
                                if gacha_name not in online_gacha_names:
                                    debug_print("Gacha", f"Adding new gacha '{gacha_name}' from set '{set_name}' with rarity '{rarity}' to online database.")
                                    await self.online_database.create_gacha_entry(name=gacha_name, set_name=set_name, rarity=rarity, local_image_path=str(gacha_file))
                                    online_gacha_names.add(gacha_name)
                                    new_gachas.append(gacha_name)
                            elif gacha_file.is_dir():
                                for subfile in gacha_file.iterdir():
                                    if subfile.is_file():
                                        gacha_name = subfile.stem.lower()
                                        local_shinies.append((gacha_name, set_name, subfile))
        new_shinies = []
        if local_shinies:
            debug_print("Gacha", f"Processing {len(local_shinies)} shiny gacha files.")
            for base_name, set_name, shiny_file in local_shinies:
                for gacha in online_gacha_list:
                    if gacha["name"].lower() == base_name and gacha["set_name"].lower() == set_name:
                        gacha_data = gacha
                        break
                if gacha_data:
                    if gacha_data["shiny_image_path"] in [None, ""]:
                        debug_print("Gacha", f"Adding shiny image for gacha '{base_name}' in set '{set_name}' to online database.")
                        await self.online_database.update_shiny_gacha_data(
                            gacha_id=gacha_data["id"],
                            set_name=set_name,
                            local_shiny_image_path=str(shiny_file),
                        )
                        new_shinies.append(f"shiny_{base_name}")
                    else:
                        continue
                else:
                    debug_print("Gacha", f"Shiny gacha '{base_name}' in set '{set_name}' has no matching normal gacha entry. Skipping shiny addition.")
        debug_print("Gacha", f"Found {len(new_gachas)} new gachas. Added {len(new_shinies)} new shinies.")
        return new_gachas
                    

    async def roll_for_gacha(self, twitch_user_id: str, twitch_display_name: str = "", num_pulls: int = 1, bits_toward_next_pull: int = 0) -> dict:
        """
        Rolls the gacha for a user a specified number of times. Defaults to 1 roll. Every 500 bits donated grants one roll. 
        So donations of 1000 bits = 2 rolls, 1500 bits = 3 rolls, etc.
        Also checks users table to see how much bits remain toward next roll and adds it to the bits_toward_next_pull parameter. Passed parameter will never exceed 400.
        If the total reaches 500, grants an additional roll and deducts 500 from the bits_toward_next_pull.
        """
        debug_print("Gacha", f"Rolling gacha for user ID: {twitch_user_id}")
        gacha_results = []
        if not self.online_database:
            self.online_database = get_reference("OnlineDatabase")
        user_data = await self.online_database.get_user_data(twitch_user_id)
        if bits_toward_next_pull > 0:
            total_bits_toward_next_pull = bits_toward_next_pull + user_data.get("bits_toward_next_gacha_pull", 0)
            if total_bits_toward_next_pull >= 500:
                num_pulls += 1
                total_bits_toward_next_pull -= 500
            await self.online_database.update_user_data(twitch_user_id, {"bits_toward_next_gacha_pull": total_bits_toward_next_pull})
        active_set = user_data.get("active_gacha_set", "humble beginnings")
        active_set, gacha_data = await self._resolve_available_gacha_set(twitch_user_id, active_set)
        if not gacha_data:
            raise RuntimeError("No enabled gacha sets are available to roll.")
        set_level = await self.online_database.get_set_level_for_user(twitch_user_id, active_set)
        set_level = min(set_level, 99)
        gacha_lookup = {gacha["id"]: gacha for gacha in gacha_data}
        rarity_index = self._build_rarity_index(gacha_data)
        pull_counts = await self.online_database.get_user_gacha_pull_counts_for_set(twitch_user_id, active_set)
        pull_counts = pull_counts or {}
        completed_set = self._is_set_completed(gacha_data, pull_counts)
        for _ in range(num_pulls):
            is_shiny = await self._calculate_shiny_chance(set_level, completed_set)
            rarity = await self._roll_for_rarity()
            gacha_pool = rarity_index.get(rarity)
            if not gacha_pool:
                debug_print("Gacha", f"No gacha found for rarity '{rarity}' in set '{active_set}'. Skipping roll.")
                continue
            selected_gacha_id, selected_gacha_name, current_level = self._select_gacha_from_pool(
                gacha_pool,
                gacha_lookup,
                pull_counts,
            )
            effective_level = min(current_level, 99)
            t = (effective_level - 1) / 98
            chance = (0.70 * (t ** 2)) * 100  #max 70% at level 99
            if randint(1, 100) <= chance:
                debug_print("Gacha", f"User ID: {twitch_user_id} triggered pity repull at level {current_level} for gacha ID: {selected_gacha_id}.")
                rarity = await self._roll_for_rarity()
                gacha_pool = rarity_index.get(rarity)
                if not gacha_pool:
                    debug_print("Gacha", f"No gacha found for rarity '{rarity}' in set '{active_set}' during pity repull.")
                    continue
                selected_gacha_id, selected_gacha_name, current_level = self._select_gacha_from_pool(
                    gacha_pool,
                    gacha_lookup,
                    pull_counts,
                )
            if is_shiny:
                if not await self._check_gacha_shiny_exists(selected_gacha_id):
                    is_shiny = False
            await self.online_database.record_gacha_pull(
                twitch_user_id=twitch_user_id,
                gacha_id=selected_gacha_id,
                is_shiny=is_shiny,
            )
            pull_counts[selected_gacha_id] = current_level + 1
            if not completed_set and self._is_set_completed(gacha_data, pull_counts):
                completed_set = True
            image_path = await self.online_storage.ensure_gacha_image(selected_gacha_id, is_shiny)
            gacha_results.append({
                "image_path": image_path,
                "is_shiny": is_shiny,
                "rarity": rarity,
                "set_name": active_set,
                "level": current_level,
                "name": selected_gacha_name
            })
            #Dictionary to return {"type": "gacha", "event_type": f"{num_pulls} gacha pulls.", "results": [gacha_results]}
        return {"type": "gacha", "event_type": f"{num_pulls} gacha pulls for {twitch_display_name if twitch_display_name else twitch_user_id}.", "results": gacha_results, "number_of_pulls": num_pulls, "user_id": twitch_user_id}
    
    async def _roll_for_rarity(self) -> Literal["UR", "SSR", "SR", "R", "N"]:
        """Rolls for a gacha rarity based on defined chances."""
        roll = random() * 100.0
        if roll < self.ur_chance:
            return "UR"
        elif roll < self.ur_chance + self.ssr_chance:
            return "SSR"
        elif roll < self.ur_chance + self.sr_chance + self.sr_chance:
            return "SR"
        elif roll < self.ur_chance + self.ssr_chance + self.sr_chance + self.r_chance:
            return "R"
        else:
            return "N"
    
    def _build_rarity_index(self, gacha_data):
        """Group gacha IDs by rarity so rolls can reuse the same pools."""
        rarity_index = {}
        for gacha in gacha_data:
            rarity_index.setdefault(gacha["rarity"], []).append(gacha["id"])
        return rarity_index
        
    def _select_gacha_from_pool(self, gacha_pool: list[int], gacha_lookup: dict, pull_counts: dict[int, int]):
        selected_gacha_id = choice(gacha_pool)
        selected_meta = gacha_lookup.get(selected_gacha_id, {})
        selected_gacha_name = selected_meta.get("name", "Unknown")
        current_level = pull_counts.get(selected_gacha_id, 0)
        return selected_gacha_id, selected_gacha_name, current_level

    async def _resolve_available_gacha_set(
        self,
        twitch_user_id: str,
        preferred_set: str | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        fallback_set = "humble beginnings"
        preferred_normalized = (preferred_set or fallback_set or "").strip() or fallback_set
        attempts: list[str] = []
        seen: set[str] = set()

        def _queue_candidate(name: str | None) -> None:
            if not name:
                return
            normalized = name.strip()
            if not normalized:
                return
            key = normalized.lower()
            if key in seen:
                return
            attempts.append(normalized)
            seen.add(key)

        _queue_candidate(preferred_normalized)
        if fallback_set:
            _queue_candidate(fallback_set)
        try:
            enabled_sets = await self.online_database.get_enabled_gacha_sets()
        except Exception as enabled_exc:
            debug_print("Gacha", f"Unable to load enabled gacha sets: {enabled_exc}")
            enabled_sets = []
        for set_name in enabled_sets:
            _queue_candidate(set_name)

        for candidate in attempts:
            try:
                data = await self.online_database.get_all_gacha_data_by_set_name(candidate)
            except Exception as load_exc:
                debug_print("Gacha", f"Failed to load gacha data for set '{candidate}': {load_exc}")
                continue
            if data:
                if candidate.lower() != preferred_normalized.lower():
                    try:
                        await self.online_database.update_user_gacha_set(twitch_user_id, candidate)
                    except Exception as update_exc:
                        debug_print("Gacha", f"Unable to update user gacha set to '{candidate}': {update_exc}")
                return candidate, data
        return preferred_normalized, []
    
    async def _calculate_shiny_chance(self, set_level: int, completed_set: bool) -> bool:
        """Calculates the shiny chance based on the user's set level and completion status."""
        try:
            normalized_level = int(set_level)
        except (TypeError, ValueError):
            normalized_level = 0
        times_to_roll = normalized_level // 2 + 1  #1 roll plus one extra roll for every 3 levels
        if normalized_level >= 99:
            times_to_roll += 5  #5 extra rolls at max level
        if completed_set:
            times_to_roll += 10  #10 extra rolls for completing the set
        for _ in range(times_to_roll):
            shiny_roll = randint(1, 8192)  #1 in 8192 chance for shiny
            if shiny_roll == 1:
                return True
        return False

    def _is_set_completed(self, gacha_data, pull_counts: dict[int, int]) -> bool:
        """Return True when the user has pulled every gacha in the provided set at least once."""
        if not gacha_data:
            return False
        return all(pull_counts.get(gacha["id"], 0) > 0 for gacha in gacha_data)
    
    async def _check_gacha_shiny_exists(self, gacha_id: int) -> bool:
        """Checks if a shiny version of the gacha exists in the online database."""
        debug_print("Gacha", f"Checking if shiny version exists for gacha ID: {gacha_id}")
        if not self.online_database:
            self.online_database = get_reference("OnlineDatabase")
        gacha_data = await self.online_database.get_gacha_data_by_id(gacha_id)
        if not gacha_data:
            debug_print("Gacha", f"Gacha with ID '{gacha_id}' does not exist in the database.")
            return False
        shiny_image_path = gacha_data.get("shiny_image_path", "")
        exists = bool(shiny_image_path)
        debug_print("Gacha", f"Shiny version exists for gacha ID: {gacha_id}: {exists}")
        return exists
    
    async def handle_gacha_event(self, event: dict) -> None:
        """Handles a gacha event by animating the gacha pulls and displaying results. Sends up to five pulls at a time to OBS for animation."""
        debug_print("Gacha", f"Handling gacha event for user ID: {event.get('user_id')} with event type: {event.get('event_type')}")
        twitch_user_id = event.get("user_id")
        gacha_results = event.get("results", [])
        if len(gacha_results) == 0:
            debug_print("Gacha", "No gacha results to handle.")
            return
        if len(gacha_results) <= 4:
            await self.animate_gacha_rolls(twitch_user_id, gacha_results)
            return
        four_results = []
        for pull in gacha_results: # Send every five pulls to animate_gacha_rolls, final batch may be less than five
            four_results.append(pull)
            if len(four_results) == 4:
                await self.animate_gacha_rolls(twitch_user_id, four_results)
                four_results = []
            elif len(four_results) > 0 and pull == gacha_results[-1]:
                await self.animate_gacha_rolls(twitch_user_id, four_results)

    async def animate_gacha_rolls(self, twitch_user_id: str, gacha_results: list[dict]) -> None:
        """
        Streams gacha rolls to the browser overlay. Supports up to five simultaneous pulls
        per animation batch. When the overlay is offline, results are logged to the console so
        staff can still verify outcomes.
        """
        debug_print("Gacha", f"Animating gacha rolls for user ID: {twitch_user_id} with {len(gacha_results)} results.")
        total_pulls = len(gacha_results)
        overlay = await self._get_overlay_bridge()
        delivered = False
        display_name = ""
        if not self.twitch_bot:
            self.twitch_bot = get_reference("TwitchBot")
        user_info = await self.twitch_bot.get_user_info_by_id(twitch_user_id)
        if user_info:
            display_name = user_info.get("display_name", "")
        if overlay:
            try:
                delivered = await overlay.send_gacha_pulls(twitch_user_id, total_pulls, gacha_results, display_name)
            except Exception as exc:
                debug_print("Gacha", f"Unable to push gacha payload to browser overlay: {exc}")
        if not delivered:
            self._log_gacha_results(twitch_user_id, gacha_results)

    async def _get_overlay_bridge(self) -> Optional[GachaOverlayBridge]:
        await self._ensure_overlay_bridge()
        return self.overlay_bridge if self.overlay_bridge and self.overlay_bridge.is_running else None

    async def _ensure_overlay_bridge(self) -> None:
        if self.overlay_bridge and self.overlay_bridge.is_running:
            return
        host_setting = GachaOverlayBridge.DEFAULT_HOST
        port_setting = GachaOverlayBridge.DEFAULT_PORT
        path_setting = GachaOverlayBridge.DEFAULT_PATH
        token_setting = ""
        host_value = (host_setting or GachaOverlayBridge.DEFAULT_HOST).strip() or GachaOverlayBridge.DEFAULT_HOST
        path_value = (path_setting or GachaOverlayBridge.DEFAULT_PATH).strip() or GachaOverlayBridge.DEFAULT_PATH
        if not path_value.startswith("/"):
            path_value = f"/{path_value}"
        token_value = (token_setting or "").strip()
        new_config = {
            "host": host_value,
            "port": int(port_setting),
            "path": path_value,
            "token": token_value,
        }
        config_changed = any(self._overlay_config.get(key) != value for key, value in new_config.items())
        if self.overlay_bridge and config_changed:
            try:
                await self.overlay_bridge.shutdown()
            except Exception as exc:
                debug_print("Gacha", f"Unable to stop previous overlay bridge: {exc}")
            self.overlay_bridge = None
        self._overlay_config = new_config
        if not self.overlay_bridge:
            try:
                self.overlay_bridge = GachaOverlayBridge(
                    host=new_config["host"],
                    port=new_config["port"],
                    path=new_config["path"],
                    auth_token=new_config["token"],
                )
                set_reference("GachaOverlay", self.overlay_bridge)
            except Exception as exc:
                debug_print("Gacha", f"Failed to instantiate overlay bridge: {exc}")
                self.overlay_bridge = None
        if self.overlay_bridge and not self.overlay_bridge.is_running:
            try:
                await self.overlay_bridge.ensure_started()
            except Exception as exc:
                debug_print("Gacha", f"Overlay bridge failed to start: {exc}")
                self.overlay_bridge = None

    def _log_gacha_results(self, twitch_user_id: str, gacha_results: list[dict]) -> None:
        if not gacha_results:
            return
        lines = [f"Gacha pulls for {twitch_user_id} (overlay offline):"]
        for idx, gacha in enumerate(gacha_results, start=1):
            name = gacha.get("name", "Unknown")
            rarity = gacha.get("rarity", "?")
            level = gacha.get("level", "?")
            shiny_flag = " ⭐" if gacha.get("is_shiny") else ""
            lines.append(f"  {idx}. {name} [{rarity}] Lv.{level}{shiny_flag}")
        summary = "\n".join(lines)
        print(summary)
        debug_print("Gacha", summary)

    async def handle_gacha_set_change(self, payload):
        """Grabs user input and checks if it's a valid gacha set, then updates the user's gacha set in the online database."""
        debug_print("Gacha", f"Handling gacha set change for user ID: {payload.user.id} with input: {payload.user_input}")
        if not self.online_database:
            self.online_database = set_reference("OnlineDatabase")
        if not self.twitch_bot:
            self.twitch_bot = get_reference("TwitchBot")
        user_input = payload.user_input.strip().lower()
        if await self.online_database.get_all_gacha_data_by_set_name(user_input) is not None:
            await self.online_database.update_user_gacha_set(payload.user.id, user_input)
            await self.twitch_bot.send_chat(f"@{payload.user.display_name}, your gacha set has been changed to '{user_input}'!")
        else:
            await payload.refund()
            await self.twitch_bot.send_chat(f"{payload.user.display_name}, the gacha set '{user_input}' does not exist or has been disabled. You have been refunded. Please try again.")
        pass  # Placeholder for gacha set change logic

    async def test(self):
        """Runs gacha roll tests for debugging purposes."""
        number_of_pulls = randint(1, 10)
        debug_print("Gacha", f"Running gacha tests with {number_of_pulls} pulls.")
        test_user_id = "test_user_123"
        results = await self.roll_for_gacha(test_user_id, number_of_pulls)
        debug_print("Gacha", f"Gacha test results: {results}")
        return results