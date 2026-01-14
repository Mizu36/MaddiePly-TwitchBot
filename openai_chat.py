import os
from openai import OpenAI
import tiktoken
import base64
import mimetypes
import asyncio
import threading
import json
import re
from dotenv import load_dotenv
from tools import debug_print, get_reference, set_reference
from db import get_prompt, get_setting

load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
BOT_DETECTION_PROMPT = {"role": "system", "content": "You are a twitch moderator who's sole job is to review a chatter's message if it is their first time chatting. You are checking if they are a bot, scammer, or spammer. You will provide a single word response, Yes, No, or Maybe. Saying Yes means you think they are a bot, scammer, or spammer. No means they are not. And Maybe means you will need more context to determine, in which case I will append more of their messages as they come in until you change your answer. Always respond with a single word, Yes, No, Maybe, so that my program can automatically take action depending on your answer."}

def num_of_tokens(messages, model: str = "gpt-4o"):
    """Return the approximate number of tokens for chat messages.

    Falls back to ``cl100k_base`` when the preferred model encoding is unavailable
    (older tiktoken builds do not ship ``o200k_base`` yet). Accuracy is sufficient
    for guardrail checks before sending prompts upstream.
    """
    debug_print("OpenAIManager", f"Calculating number of tokens for messages with model: {model}")

    def _get_encoding():
        attempts = [
            lambda: tiktoken.encoding_for_model(model),
            lambda: tiktoken.get_encoding("o200k_base"),
            lambda: tiktoken.get_encoding("cl100k_base"),
            lambda: tiktoken.get_encoding("p50k_base"),
            lambda: tiktoken.get_encoding("r50k_base"),
        ]
        for factory in attempts:
            try:
                return factory()
            except Exception as exc:
                print("OpenAIManager", f"Token encoding attempt failed: {exc}")

        class _ApproxEncoding:
            def encode(self, text):
                if text is None:
                    return []
                length = len(str(text))
                approx = max(1, length // 4)
                return [0] * approx

        debug_print("OpenAIManager", "Falling back to approximate token counting.")
        return _ApproxEncoding()

    encoding = _get_encoding()

    def _encode_length(value) -> int:
        if value is None:
            return 0
        if isinstance(value, str):
            return len(encoding.encode(value))
        if isinstance(value, dict):
            return sum(_encode_length(v) for v in value.values())
        if isinstance(value, list):
            return sum(_encode_length(v) for v in value)
        return len(encoding.encode(str(value)))

    num_tokens = 0
    for message in messages or []:
        num_tokens += 4  # every message follows <im_start>{role/name}\n{content}<im_end>\n
        if isinstance(message, dict):
            for key, value in message.items():
                num_tokens += _encode_length(value)
                if key == "name":
                    num_tokens -= 1  # role is omitted when name is present
    num_tokens += 2  # every reply is primed with <im_start>assistant
    return num_tokens
  

class OpenAiManager:
    
    def __init__(self):
        set_reference("GPTManager", self)
        self.prompts = []
        self.default_model = None
        self.fine_tune_model = None
        self.bot_detector_model = None
        self.assistant = get_reference("AssistantManager")
        try:
            self.client = OpenAI(api_key = API_KEY)
        except TypeError:
            exit("[ERROR]Ooops! You forgot to set OPENAI_API_KEY in your environment!")
        debug_print("OpenAIManager", "OpenAI Manager initialized.")
        self.memory_summarization_prompt = {"role": "system", "content": "TASK: Summarize recent interactions into long-term memory for MaddiePly.\n\nYou are NOT responding to chat.\nYou are converting raw conversation and events into structured memory.\n\nIMPORTANT CONSTRAINTS:\n- Do NOT write dialogue.\n- Do NOT include quotes.\n- Do NOT roleplay or add personality flair.\n- Do NOT invent facts.\n- Do NOT include formatting rules or instructions.\n- Write in neutral, factual language only.\n\nMEMORY MUST:\n- Contain only information useful for future interactions.\n- Preserve continuity of relationships, running jokes, and ongoing themes.\n- Exclude one-off chatter unless it became a repeated topic.\n\nCategorize information under the following sections ONLY if applicable:\n\nLORE:\n- Persistent facts about ModdCorp, MaddiePly, or internal canon established during interactions.\n\nRELATIONSHIPS:\n- Notable changes or patterns in how MaddiePly interacts with ModdiPly or chat.\n- Recurring viewers, roles, or reputations if relevant.\n\nUSER PREFERENCES:\n- Style, tone, or behavior the audience responds well or poorly to.\n- Repeated requests or corrections from ModdiPly.\nRUNNING JOKES & THEMES:\n- Repeated gags, policies, fictional projects, or terminology that reoccur.\n\nOPEN THREADS:\n- Unresolved topics, promises, or ongoing arcs likely to continue.\n\nAVOID STORING:\n- Exact wording of messages.\n- Temporary emotions.\n- Redundant restatements of personality.\n- Output formatting constraints.\n\nIf no meaningful long-term memory was created, respond with:\nNO UPDATE "}
        self.tool_prompt = {"role": "system", "content": "TASK: Decide if a tool is required before responding.\n\nYou are NOT speaking to chat.\nYou are selecting a tool or NONE.\n\nRULES:\n- Choose ONE tool or NONE.\n- Do not explain your choice.\n- Do not roleplay.\n- Output JSON only in the exact schema provided.\n\nSchema:\n{\n  \"tool\": \"NONE | SEARCH_WEB | SCREENSHOT_DESKTOP | SCREENSHOT_STREAM\",\n  \"argument\": \"string or null\" \n}"}
        self.working_memory = ""
        self.twitch_emotes_prompt = None

    async def set_models(self):
        """Sets the OpenAI model to use for chat."""
        debug_print("OpenAIManager", "Fetching OpenAI models from settings.")
        self.default_model = await get_setting("Default OpenAI Model")
        self.fine_tune_model = await get_setting("Fine-tune GPT Model")
        self.bot_detector_model = await get_setting("Fine-tune Bot Detection Model")

    async def prepare_history(self):
        """Prepares all chat histories with system prompts."""
        self.personality_prompt = await get_prompt("Personality Prompt")
        self.global_output_rules = await get_prompt("Global Output Rules")
        self.prompts = [{"role": "system", "content": self.personality_prompt}, {"role": "system", "content": self.global_output_rules}]
        self.twitch_emotes_prompt = {"role": "system", "content": await get_prompt("Twitch Emotes")}

    def summarize_memory(self, recent_interaction: str) -> None:
        debug_print("OpenAIManager", "Summarizing recent interactions into long-term memory.")
        prompt = {"role": "system", "content": f"CURRENT MEMORY:\n{self.working_memory if self.working_memory else 'NONE'}\n\nRECENT EVENTS (RAW):\n{recent_interaction}"}
        messages = [{"role": "system", "content": self.personality_prompt}, self.memory_summarization_prompt, prompt]
        try:
            completion = self.client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=messages,
                            temperature=0.3,
                            top_p=0.8,
                            presence_penalty=0.0,
                            frequency_penalty=0.0
                            )
            openai_answer = completion.choices[0].message.content
            debug_print("OpenAIManager", f"Memory summarization response: {openai_answer}")
            if openai_answer.strip() != "NO UPDATE":
                self.working_memory = openai_answer
        except Exception as e:
            print(f"[ERROR]Failed to get response from OpenAI for memory summarization: {e}")
            return
        
    def handle_chat(self, task_prompt: dict | None, context_prompt: dict, use_twitch_emotes = False, use_personality = True):
        tool_decision = self.perform_tool_selection(context_prompt)

        tool_result_prompt = None

        if tool_decision["tool"] != "NONE":
            tool_output = self.execute_tool(
                tool_decision["tool"],
                tool_decision["argument"]
            )
            tool_result_prompt = {
                "role": "system",
                "content": f"TOOL RESULT:\n{tool_output}"
            }

        prompts = []
        if task_prompt:
            prompts.append(task_prompt)
        prompts.append(context_prompt)

        if tool_result_prompt:
            prompts.insert(-1, tool_result_prompt)

        return self.chat(prompts, conversational=False, use_twitch_emotes=use_twitch_emotes, use_personality=use_personality)
    
    def execute_tool(self, tool_name: str, argument: str) -> str:
        debug_print("OpenAIManager", f"Executing tool: {tool_name} with argument: {argument}")
        if not self.assistant:
            self.assistant = get_reference("AssistantManager")
        tool_output = ""
        if tool_name == "SEARCH_WEB":
            tool_output = self.assistant.search_web(argument)
        elif tool_name == "SCREENSHOT_DESKTOP":
            tool_output = self.assistant.screenshot_desktop()
        elif tool_name == "SCREENSHOT_STREAM":
            tool_output = self.assistant.screenshot_stream()
        elif tool_name == "QUERY_MEMORY":
            pass #Unused
        else:
            tool_output = "[UNKNOWN TOOL]"
        return tool_output

    def chat(self, prompts: list[dict], conversational: bool = False, use_twitch_emotes: bool = False, use_personality: bool = True) -> str:
        """Asks a question to OpenAI's chat model after passing a system prompt and user prompt. Only two prompts should be passed in the list.
        If conversational is True, uses the fine-tuned model for more conversational responses."""
        debug_print("OpenAIManager", f"Asking chat question, conversational={conversational}.")
        if not prompts or not isinstance(prompts, list):
            print("[ERROR]Didn't receive input!")
            return
        
        if not use_personality:
            completion = self.client.chat.completions.create(
                            model="gpt-4o",
                            messages=prompts,
                            temperature=0.85,
                            top_p=0.95,
                            presence_penalty=0.3,
                            frequency_penalty=0.2
                            )
            openai_answer = completion.choices[0].message.content
            deformatted_answer = openai_answer.replace('—', ' ').strip()
            print(f"{'MaddiePly says:\n' if use_personality else 'ChatGPT says:\n'}{openai_answer}")
            return deformatted_answer
        else:
            pass
        working_memory_prompt = {"role": "system", "content": f"MEMORY (REFERENCE ONLY):\n{self.working_memory if self.working_memory else 'NONE'}"}
        prompts.insert(1, working_memory_prompt)
        messages = self.prompts + prompts
        if use_twitch_emotes:
            messages.insert(2, self.twitch_emotes_prompt)
        model = None
        if conversational:
            model = self.fine_tune_model if self.fine_tune_model else self.default_model
            if not model:
                model = "gpt-4o"
        else:
            model = self.default_model if self.default_model else "gpt-4o"
        #debug_print("OpenAIManager", f"{messages}")
        print("Asking ChatGPT a question...")
        # Process the answer
        try:
            completion = self.client.chat.completions.create(
                            model=model,
                            messages=messages,
                            temperature=0.85,
                            top_p=0.9
                            )
        except Exception:
            try:
                completion = self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages,
                    temperature=0.85,
                    top_p=0.9
                    )
            except Exception as e:
                print(f"[ERROR]Failed to get response from OpenAI: {e}")
                return
        openai_answer = completion.choices[0].message.content
        deformatted_answer = openai_answer.replace('—', ' ').strip()
        user_input_prompt = prompts[-1]["content"]
        recent_interaction = f"{user_input_prompt}\nMaddiePly's Response: {openai_answer}"
        self._schedule_memory_summary(recent_interaction)
        debug_print("OpenAIManager", f"{openai_answer}")
        return deformatted_answer
    
    def perform_tool_selection(self, context_prompt: dict) -> dict:
        """Asks the tool selection prompt to OpenAI's chat model to determine if a tool is needed."""
        debug_print("OpenAIManager", f"Asking tool selection question.")
        messages = [
            {
                "role": "system",
                "content": "You are selecting tools. You are not responding to chat."
            },
            {
                "role": "system",
                "content": f"CURRENT MEMORY:\n{self.working_memory if self.working_memory else 'NONE'}"
            },
            context_prompt,
            self.tool_prompt
        ]
        print("Asking ChatGPT for tool selection...")
        # Process the answer
        try:
            completion = self.client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=messages,
                            temperature=0.0,
                            top_p=1.0,
                            presence_penalty=0.0,
                            frequency_penalty=0.0
                            )
        except Exception:
            try:
                completion = self.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=messages,
                    temperature=0.0,
                    top_p=1.0,
                    presence_penalty=0.0,
                    frequency_penalty=0.0
                    )
            except Exception as e:
                print(f"[ERROR]Failed to get response from OpenAI: {e}")
                return {"tool": "NONE", "argument": None}
        openai_answer = completion.choices[0].message.content
        debug_print("OpenAIManager", f"Tool selection response: {openai_answer}")
        parsed = self._parse_tool_response(openai_answer)
        return parsed if parsed else {"tool": "NONE", "argument": None}

    def _schedule_memory_summary(self, recent_interaction: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            threading.Thread(
                target=self.summarize_memory,
                args=(recent_interaction,),
                daemon=True,
            ).start()
            return
        loop.create_task(asyncio.to_thread(self.summarize_memory, recent_interaction))
    
    def bot_detector(self, message: str, model: str = None):
        debug_print("OpenAIManager", f"Running bot detection on message.")
        if not message:
            debug_print("OpenAIManager", "Called without input!")
            return
        
        messages = [BOT_DETECTION_PROMPT, {"role": "user", "content": message}]

        completion = self.client.chat.completions.create(
            model = model if model else "ft:gpt-4o-mini-2024-07-18:mizugaming:bot-detector:Bv9zPaZq",
            messages=messages
        )
        openai_answer = completion.choices[0].message.content
        print(openai_answer)

        if openai_answer.lower().startswith("yes"):
            debug_print("OpenAIManager", f"Suspicious message is spam.")
            return True
        elif openai_answer.lower().startswith("no"):
            debug_print("OpenAIManager", f"Suspicious message is not spam.")
            return False
        elif openai_answer.lower().startswith("maybe"):
            debug_print("OpenAIManager", f"Not sure if suspicious message is spam.")
            return 3
        else:
            debug_print("OpenAIManager", f"Invalid response from bot-detection AI: {openai_answer}")
            return 3
        
    def analyze_image(self, image_path: str, is_meme: bool = False):
        if not image_path:
            print("Didn't receive an image path!")
            return

        try:
            # Guess the MIME type (e.g. "image/jpeg", "image/png")
            content_type, _ = mimetypes.guess_type(image_path)
            if content_type is None:
                content_type = "image/jpeg"  # default fallback

            # Read file as bytes
            with open(image_path, "rb") as f:
                image_bytes = f.read()

            debug_print("OpenAIManager", "Asking ChatGPT to analyze a local image...")

            base64_image = base64.b64encode(image_bytes).decode("utf-8")

            if not is_meme:
                completion = self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Describe this image in detail. Do not describe the overlay, but instead the focus of the image (gameplay, movie, media). "
                                "If the image contains a tabby cat, the cat's "
                                "name is Junebug, include that in the description. If you recognize any characters "
                                "from popular media, include that in the description. "
                                "Focus on describing actions or events happening in the image. "
                                "The character adorned in mostly blue, sitting at a desk is ModdiPly."
                                "Do not describe ModdiPly, the desk, Junebug, or any overlays. "
                            )
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{content_type};base64,{base64_image}",
                                        "detail": "auto"
                                    }
                                }
                            ]
                        }
                    ]
                )
            else:
                completion = self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are MaddiePly, a witty and sarcastic AI who creates funny meme captions. "
                                "Create a funny meme caption for the image provided. "
                                "The caption should be witty and relevant to the content of the image. "
                                "Do not use any emojis or special characters. "
                                "Keep it concise and humorous. "
                                "Feel free to use blank lines for comedic effect. "
                                "Feel free to make pop culture references if appropriate. "
                                "Feel free to go weird and silly!"
                                "Only responde with the caption text and the font using the following format: "
                                "!caption <your caption here> "
                                "!font <font name here> "
                                "Here is an example response: "
                                "!caption when you realize it's Monday tomorrow "
                                "!font impact.ttf"
                            )
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{content_type};base64,{base64_image}",
                                        "detail": "auto"
                                    }
                                }
                            ]
                        }
                    ]
                )

        except Exception as e:
            print(f"Error analyzing image: {e}")
            return

        # Process the answer
        openai_answer = completion.choices[0].message.content
        print(f"{openai_answer}")
        return openai_answer
    
    def get_all_models(self):
        debug_print("OpenAIManager", "Fetching available OpenAI models.")
        return ["gpt-3.5-turbo", "gpt-4", "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-pro", "gpt-5.1", "o3", "o3-mini", "o4-mini"]
    
    def _parse_tool_response(self, response: str | None) -> dict | None:
        if not response:
            return None
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z0-9]*\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        candidate = cleaned if start == -1 or end == -1 or end < start else cleaned[start:end+1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        # Fallback: allow single-quoted dicts
        alt = candidate.replace("'", '"')
        try:
            return json.loads(alt)
        except json.JSONDecodeError:
            return None
    

if __name__ == "__main__":
    gpt_manager = OpenAiManager()
        