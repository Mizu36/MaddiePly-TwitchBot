from tools import get_reference, set_reference, debug_print, get_app_root
from pathlib import Path
from random import randint, random, choice
from typing import Literal

class Gacha():
    def __init__(self):
        set_reference("GachaHandler", self)
        self.online_database = get_reference("OnlineDatabase")
        self.online_storage = get_reference("OnlineStorage")
        self.twitch_bot = get_reference("TwitchBot")
        self.obs = get_reference("OBSManager")
        self.ur_chance = 0.35
        self.ssr_chance = 1.75
        self.sr_chance = 7.9
        self.r_chance = 25.0
        self.local_gacha_path = Path(get_app_root()) / "media" / "gacha"
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
        online_gacha_list = await self.online_database.get_all_gacha_data()
        online_gacha_names = {gacha["name"].lower() for gacha in online_gacha_list}
        if not self.local_gacha_path.exists():
            self.local_gacha_path.mkdir(parents=True, exist_ok=True)
            debug_print("Gacha", f"Created missing gacha directory at {self.local_gacha_path}.")
            return
        
        shinies = []
        debug_print("Gacha", f"Scanning local gacha directory at {self.local_gacha_path} for gacha files.")
        for set_folder in self.local_gacha_path.iterdir():
            if set_folder.name.lower() == "animations":
                continue
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
                                if gacha_name.startswith("shiny_"):
                                    shinies.append((gacha_name[6:], set_name, gacha_file))  #store shiny gacha to process later
                                    continue
                                if gacha_name not in online_gacha_names:
                                    debug_print("Gacha", f"Adding missing gacha '{gacha_name}' from set '{set_name}' with rarity '{rarity}' to online database.")
                                    await self.online_database.create_gacha_entry(name=gacha_name, set_name=set_name, rarity=rarity, local_image_path=str(gacha_file))
                                    online_gacha_names.add(gacha_name)

        if shinies:
            debug_print("Gacha", f"Processing {len(shinies)} shiny gacha files.")
            for base_name, set_name, shiny_file in shinies:
                gacha_data = await self.online_database.get_gacha_data_by_name(base_name)
                if gacha_data and gacha_data.get("set_name", "").lower() == set_name:
                    debug_print("Gacha", f"Adding shiny image for gacha '{base_name}' in set '{set_name}' to online database.")
                    await self.online_database.update_shiny_gacha_data(
                        gacha_id=gacha_data["id"],
                        set_name=set_name,
                        local_shiny_image_path=str(shiny_file),
                    )
                else:
                    debug_print("Gacha", f"Shiny gacha '{base_name}' in set '{set_name}' has no matching normal gacha entry. Skipping shiny addition.")
        debug_print("Gacha", "Completed processing gacha files.")

    async def check_for_new_gacha(self) -> list[str]:
        """Called from a button on the GUI to check for new gacha files added to the local gacha folder, 
        then adds them to the online database and uploads the images to storage."""
        debug_print("Gacha", "Checking for new gacha files in local gacha directory.")
        shinies = []
        if not self.online_database:
            self.online_database = get_reference("OnlineDatabase")
        if not self.online_storage:
            self.online_storage = get_reference("OnlineStorage")
        online_gacha_list = await self.online_database.get_all_gacha_data()
        online_gacha_names = {gacha["name"].lower() for gacha in online_gacha_list}
        new_gachas = []
        for set_folder in self.local_gacha_path.iterdir():
            if set_folder.name.lower() == "animations":
                continue
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
                                if gacha_name.startswith("shiny_"):
                                    shinies.append((gacha_name[6:], set_name, gacha_file))  #store shiny gacha to process later
                                    continue
                                if gacha_name not in online_gacha_names:
                                    debug_print("Gacha", f"Adding new gacha '{gacha_name}' from set '{set_name}' with rarity '{rarity}' to online database.")
                                    await self.online_database.create_gacha_entry(name=gacha_name, set_name=set_name, rarity=rarity, local_image_path=str(gacha_file))
                                    online_gacha_names.add(gacha_name)
                                    new_gachas.append(gacha_name)
        if shinies:
            debug_print("Gacha", f"Processing {len(shinies)} shiny gacha files.")
            for base_name, set_name, shiny_file in shinies:
                gacha_data = await self.online_database.get_gacha_data_by_name(base_name)
                if gacha_data and gacha_data.get("set_name", "").lower() == set_name:
                    debug_print("Gacha", f"Adding shiny image for gacha '{base_name}' in set '{set_name}' to online database.")
                    await self.online_database.update_shiny_gacha_data(
                        gacha_id=gacha_data["id"],
                        set_name=set_name,
                        local_shiny_image_path=str(shiny_file),
                    )
                else:
                    debug_print("Gacha", f"Shiny gacha '{base_name}' in set '{set_name}' has no matching normal gacha entry. Skipping shiny addition.")
        debug_print("Gacha", f"Found {len(new_gachas)} new gachas.")
        return new_gachas
                    

    async def roll_for_gacha(self, twitch_user_id: str, num_pulls: int = 1, bits_toward_next_pull: int = 0) -> dict:
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
        set_level = await self.online_database.get_set_level_for_user(twitch_user_id, active_set)
        set_level = min(set_level, 99)
        gacha_data = await self.online_database.get_all_gacha_data_by_set_name(active_set) # [{"id": int, "name": str, "set_name": str, "rarity": str, "pulled": int, "image_path": str, "shiny_image_path": str}, ...]
        if not gacha_data:
            debug_print("Gacha", f"No gacha data found for set '{active_set}'.")
            await self.online_database.update_user_gacha_set(twitch_user_id, "humble beginnings")
            gacha_data = await self.online_database.get_all_gacha_data_by_set_name("humble beginnings")
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
        return {"type": "gacha", "event_type": f"{num_pulls} gacha pulls.", "results": gacha_results, "number_of_pulls": num_pulls, "user_id": twitch_user_id}
    
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
    
    async def _calculate_shiny_chance(self, set_level: int, completed_set: bool) -> bool:
        """Calculates the shiny chance based on the user's set level and completion status."""
        times_to_roll = set_level // 2 + 1  #1 roll plus one extra roll for every 3 levels
        if set_level == 99:
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
        if len(gacha_results) <= 5:
            await self.animate_gacha_rolls(twitch_user_id, gacha_results)
            return
        five_results = []
        for pull in gacha_results: # Send every five pulls to animate_gacha_rolls, final batch may be less than five
            five_results.append(pull)
            if len(five_results) == 5:
                await self.animate_gacha_rolls(twitch_user_id, five_results)
                five_results = []
            elif len(five_results) > 0 and pull == gacha_results[-1]:
                await self.animate_gacha_rolls(twitch_user_id, five_results)

    async def animate_gacha_rolls(self, twitch_user_id: str, gacha_results: list[dict]) -> None:
        """
        Animates the gacha rolls using OBS and displays results. Will animate a max of five rolls simultaneously. 
        If passed more than five rolls, will queue them up in groups of five. Sends a list of dictionaries with gacha_lvl, rarity, is_shiny, image_path, name
        """
        debug_print("Gacha", f"Animating gacha rolls for user ID: {twitch_user_id} with {len(gacha_results)} results.")
        if not self.obs:
            self.obs = get_reference("OBSManager")
        total_pulls = len(gacha_results)
        await self.obs.animate_gacha_pulls(twitch_user_id, total_pulls, gacha_results)

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