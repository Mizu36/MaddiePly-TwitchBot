import os
from openai import OpenAI
import tiktoken
import base64
import mimetypes
from dotenv import load_dotenv
from tools import debug_print
from db import get_setting

load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
BOT_DETECTION_PROMPT = {"role": "system", "content": "You are a twitch moderator who's sole job is to review a chatter's message if it is their first time chatting. You are checking if they are a bot, scammer, or spammer. You will provide a single word response, Yes, No, or Maybe. Saying Yes means you think they are a bot, scammer, or spammer. No means they are not. And Maybe means you will need more context to determine, in which case I will append more of their messages as they come in until you change your answer. Always respond with a single word, Yes, No, Maybe, so that my program can automatically take action depending on your answer."}

def num_of_tokens(messages, model = None):
  """Returns the number of tokens used by a list of messages.
  Copied with minor changes from: https://platform.openai.com/docs/guides/chat/managing-tokens """
  debug_print("OpenAIManager", f"Calculating number of tokens for messages with model: {model}")
  try:
      encoding = tiktoken.get_encoding("o200k_base")
      num_tokens = 0
      for message in messages:
          num_tokens += 4  # every message follows <im_start>{role/name}\n{content}<im_end>\n
          for key, value in message.items():
              num_tokens += len(encoding.encode(value))
              if key == "name":  # if there's a name, the role is omitted
                  num_tokens += -1  # role is always required and always 1 token
      num_tokens += 2  # every reply is primed with <im_start>assistant
      return num_tokens
  except Exception:
      raise NotImplementedError(f"""[ERROR]num_tokens_from_messages() is not presently implemented for model {model}.
      #See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens.""")
  

class OpenAiManager:
    
    def __init__(self):
        self.chat_history = [] # Stores the entire conversation
        self.twitch_chat_history = [] # Stores the conversation history for Twitch chat
        self.default_model = None
        self.fine_tune_model = None
        self.bot_detector_model = None
        try:
            self.client = OpenAI(api_key = API_KEY)
        except TypeError:
            exit("[ERROR]Ooops! You forgot to set OPENAI_API_KEY in your environment!")
        debug_print("OpenAIManager", "OpenAI Manager initialized.")

    async def set_models(self):
        """Sets the OpenAI model to use for chat."""
        debug_print("OpenAIManager", "Fetching OpenAI models from settings.")
        self.default_model = await get_setting("Default OpenAI Model")
        self.fine_tune_model = await get_setting("Fine-tune GPT Model")
        self.bot_detector_model = await get_setting("Fine-tune Bot Detection Model")

    def add_personality_to_history(self, personality_prompt: str, twitch_emotes: str):
        """Adds a system prompt to the chat history to set the bot's personality."""
        debug_print("OpenAIManager", "Adding personality prompt to chat history.")
        self.twitch_chat_history.append({"role": "system", "content": personality_prompt})
        self.twitch_chat_history.append({"role": "system", "content": twitch_emotes})
        self.chat_history.append({"role": "system", "content": personality_prompt})

    # Asks a question with no chat history
    def chat(self, messages, conversational: bool, model: str = None) -> str:
        debug_print("OpenAIManager", f"Asking chat question without history, conversational={conversational}.")
        if not messages or not isinstance(messages, list):
            print("[ERROR]Didn't receive input!")
            return

        # Check that the prompt is under the token context limit
        if num_of_tokens(messages) > 4000:
            print("[WARNING]The length of this chat question is too large for the GPT model")
            return

        debug_print("OpenAIManager", "Asking ChatGPT a question...")



        # Process the answer
        try:
            completion = self.client.chat.completions.create(
                            model=self.fine_tune_model if conversational else self.default_model,
                            messages=messages
                            )
        except Exception:
            try:
                completion = self.client.chat.completions.create(
                    model=self.default_model if self.default_model else "gpt-4o",
                    messages=messages
                    )
            except Exception as e:
                print(f"[ERROR]Failed to get response from OpenAI: {e}")
                return
        openai_answer = completion.choices[0].message.content
        debug_print("OpenAIManager", f"{openai_answer}")
        return openai_answer
    

    # Asks a question that includes the full conversation history
    def chat_with_history(self, prompt="", conversational: bool = False, twitch_chat: bool = False, model: str = None) -> str:
        debug_print("OpenAIManager", f"Asking chat question with history, conversational={conversational}, twitch_chat={twitch_chat}.")
        if not prompt:
            print("[ERROR]Didn't receive input!")
            return
        
        # Add our prompt into the chat history
        if twitch_chat:
            self.twitch_chat_history.append({"role": "user", "content": prompt})
        else:
            self.chat_history.append({"role": "user", "content": prompt})

        # Check total token limit. Remove old messages as needed
        debug_print("OpenAIManager", f"Chat History has a current token length of {num_of_tokens(self.chat_history)}")
        if not twitch_chat:
            while num_of_tokens(self.chat_history) > 2000:
                self.chat_history.pop(1) # We skip the 1st message since it's the system message
                debug_print("OpenAIManager", f"Popped a message! New token length is: {num_of_tokens(self.chat_history)}")
        else:
            while num_of_tokens(self.twitch_chat_history) > 4000:
                self.twitch_chat_history.pop(1)

        debug_print("OpenAIManager", "Asking ChatGPT a question...")

        # Use the correct chat history
        if twitch_chat:
            messages = self.twitch_chat_history
        else:
            messages = self.chat_history
        # Add this answer to our chat history
        try:
            completion = self.client.chat.completions.create(
                            model=self.fine_tune_model if conversational else self.default_model,
                            messages=messages
                            )
        except Exception:
            try:
                completion = self.client.chat.completions.create(
                    model=self.default_model if self.default_model else "gpt-4o",
                    messages=messages
                    )
            except Exception as e:
                print(f"[ERROR]Failed to get response from OpenAI: {e}")
                return
        
        if twitch_chat:
            self.twitch_chat_history.append({"role": completion.choices[0].message.role, "content": completion.choices[0].message.content})
        else:
            self.chat_history.append({"role": completion.choices[0].message.role, "content": completion.choices[0].message.content})

        # Process the answer
        openai_answer = completion.choices[0].message.content
        debug_print("OpenAIManager", f"{openai_answer}")
        return openai_answer
    
    def bot_detector(self, message: str, model: str = None):
        debug_print("OpenAIManager", f"Running bot detection on message.")
        if not message:
            debug_print("OpenAIManager", "Called without input!")
            return
        
        messages = [BOT_DETECTION_PROMPT, {"role": "user", "content": message}]

        completion = self.client.chat.completions.create(
            model = "ft:gpt-4o-mini-2024-07-18:mizugaming:bot-detector:Bv9zPaZq",
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
    

if __name__ == "__main__":
    gpt_manager = OpenAiManager()
    #gpt_manager.get_and_analyze_screenshot("moddiply")
    #gpt_manager.bot_detector("Check out this cool site: bit.ly/xyz")
    #gpt_manager.bot_detector("Hello, how are you?")
    print(gpt_manager.chat_with_history("Hello, how are you?", conversational=True))
        