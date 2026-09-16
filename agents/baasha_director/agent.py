import os
import base64
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset, SseConnectionParams
from google.genai import types

os.environ["GEMINI_API_KEY"] = "AIzaSyCmKkswlaMbn039z-wdx8IkADslR8DJVTs"


async def promote_images_to_artifacts(tool, args, tool_context, tool_response):
    """
    Middleware to intercept tool outputs. If it contains MCP image data,
    we save it as an ADK Artifact so it's visible in the UI explorer.
    """
    if isinstance(tool_response, dict) and "content" in tool_response:
        content = tool_response.get("content", [])
        for i, item in enumerate(content):
            if isinstance(item, dict) and item.get("type") == "image":
                try:
                    b64_data = item.get("data")
                    if not b64_data:
                        continue
                    mime_type = item.get("mimeType", "image/jpeg")
                    image_bytes = base64.b64decode(b64_data)

                    # Save to ADK Artifact Service
                    # Use function_call_id to prevent filename collisions across different audits
                    filename = f"audit_{tool_context.function_call_id}_{i}.jpg"
                    await tool_context.save_artifact(
                        filename=filename,
                        artifact=types.Part.from_bytes(
                            data=image_bytes, mime_type=mime_type
                        ),
                    )
                except Exception as e:
                    print(f"Failed to promote image to artifact: {e}")
    return tool_response


# 1. Connect to your Baasha MCP running over SSE
baasha_mcp_config = SseConnectionParams(url="http://localhost:8000/sse")
baasha_tools = McpToolset(connection_params=baasha_mcp_config)

# 2. Configure the Gemini Agent
root_agent = LlmAgent(
    name="baasha_creative_director",
    model="gemini-3-flash-preview",
    instruction=(
        "You are the Creative Partner and Design Assistant in a high-fidelity video production studio. "
        "Your goal is to empower creators and designers to ideate, explore, and polish their vision. "
        "DO NOT rush to complete the video. Instead, work iteratively: "
        "1. IDEATE: Use 'search_web' and 'get_similar_creative_ideas' to find themes and precursors. "
        "2. EXPLORE: Use 'generate_moodboard' to propose stylistic directions. Ask the user which 'vibe' they want to lock in. "
        "3. DRAFT & REVIEW: Build the video in stages (STORY, then IMAGES). Stop and ask for feedback after each milestone. "
        "4. AUDIT: When you call 'view_images', provide a professional critique. Ask the designer: 'How does this look? Should we pivot the lighting (Stage 2) or refine the script (Stage 0)?' "
        "5. REFINE: Use 'refine_draft' for surgical fixes based on user critique. "
        "The Designer is the final judge. Your value is in exploration, suggestions, and doing it 'right', not just doing it 'fast'."
    ),
    tools=[baasha_tools],
    after_tool_callback=promote_images_to_artifacts,
)
