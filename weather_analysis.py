import os
import base64
from openai import OpenAI

# ---------------------------------------------------------
# 1. Load Hugging Face token (hardcoded or environment var)
# ---------------------------------------------------------
HF_TOKEN = os.environ.get("HF_TOKEN", "")

vision_client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_TOKEN,
)

reasoning_client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_TOKEN,
)

# ---------------------------------------------------------
# 2. Helper: Encode images to Base64
# ---------------------------------------------------------
def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

img1 = encode_image("static/assets/MaxT1_conus.png")
img2 = encode_image("static/assets/national_forecast.jpg")

# ---------------------------------------------------------
# 3. Step A — Vision model extracts weather information
# ---------------------------------------------------------
vision_response = vision_client.chat.completions.create(
    model="Qwen/Qwen2-VL-7B-Instruct",
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": f"data:image/png;base64,{img1}"},
                {"type": "input_image", "image_url": f"data:image/png;base64,{img2}"},
                {
                    "type": "text",
                    "text": (
                        "Analyze both weather maps. Extract all visible information: "
                        "precipitation zones, temperature patterns, pressure systems, "
                        "fronts, hazards, and regional differences. Provide a clean, "
                        "structured summary of what each map shows."
                    )
                }
            ]
        }
    ]
)

vision_output = vision_response.choices[0].message["content"]

# ---------------------------------------------------------
# 4. Step B — DeepSeek-R1 performs reasoning + breakdown
# ---------------------------------------------------------
reasoning_response = reasoning_client.chat.completions.create(
    model="deepseek-ai/DeepSeek-R1:novita",
    messages=[
        {
            "role": "user",
            "content": (
                "Here is extracted weather-map information:\n\n"
                f"{vision_output}\n\n"
                "Using this information, produce a detailed, structured Regional Breakdown. "
                "Identify precipitation types, severe weather zones, pressure systems, "
                "temperature patterns, and major differences between the two maps."
            )
        }
    ]
)

final_output = reasoning_response.choices[0].message["content"]

# ---------------------------------------------------------
# 5. Print final result
# ---------------------------------------------------------
print("\n===== FINAL REGIONAL BREAKDOWN =====\n")
print(final_output)