import logging
from baasha_pipeline.chatbot import ChatInterface
from baasha_pipeline.configs import app_config as baasha_pipeline_config
from baasha_pipeline.prompts.splitters import markdown_parse
import configparser

logger = logging.getLogger(__name__)

config = configparser.ConfigParser()
config.read("config.ini")

baasha_pipeline_auth_config = baasha_pipeline_config.get()["auth"]
baasha_pipeline_auth_config["google_genai_key"] = config["SECRETS"][
    "GOOGLE_GENAI_KEY"
].split(", ")
baasha_pipeline_config.set("auth", baasha_pipeline_auth_config)


def create_documentation():
    """
    Generates updated documentation for the project using an LLM.

    Args:
        llm_model (str): The name of the LLM model to use (default: "groq").

    Returns:
        str: A markdown string containing the updated documentation.
    """

    # 1. Read Files
    try:
        with open("API_DOC.md", "r") as f:
            api_doc = f.read()
    except FileNotFoundError:
        api_doc = ""

    try:
        with open("server.py", "r") as f:
            server_code = f.read()
    except FileNotFoundError:
        server_code = ""

    try:
        with open("parsers.py", "r") as f:
            parsers_code = f.read()
    except FileNotFoundError:
        parsers_code = ""

    # 2. Extract Information
    api_endpoints = extract_api_endpoints(server_code)
    data_structures = extract_data_structures(parsers_code)

    # 3. Prompt LLM
    prompt = f"""
    You are an AI documentation generator. Please update the API documentation based on the following information.

    Existing Documentation (API_DOC.md):
    {api_doc}

    API Endpoints (from server.py):
    {api_endpoints}

    Data Structures (from parsers.py):
    {data_structures}

    Please provide a detailed and well-formatted markdown document that includes:
    - An overview of the API.
    - Detailed descriptions of each endpoint, including request parameters and response formats.
    - Clear explanations of the data structures used in the API.
    - Examples of how to use the API.
    - Understand logic completed and document the nuances to use the API.
    - Be as thorough and detailed as possible.

    Make sure to integrate the existing documentation and update it with the new API endpoints and data structures.
    """

    chatbot = ChatInterface("gemini-2.5-pro-exp-03-25")
    chatbot.new_conversation()
    documentation = chatbot.fetch_text(prompt)
    chatbot.delete_conversation()

    output = markdown_parse(documentation, lang="markdown")

    # 4. Return Documentation
    return output


def extract_api_endpoints(server_code):
    """
    Extracts API endpoints from the server.py code.
    This is a placeholder and needs to be implemented using proper code parsing techniques (e.g., AST).
    """
    # TODO: Implement proper endpoint extraction using AST or regex
    # For now, return a placeholder
    return server_code


def extract_data_structures(parsers_code):
    """
    Extracts data structures from the parsers.py code.
    This is a placeholder and needs to be implemented using proper code parsing techniques (e.g., AST).
    """
    # TODO: Implement proper data structure extraction using AST or regex
    # For now, return a placeholder
    return parsers_code


if __name__ == "__main__":
    documentation = create_documentation()
    logger.info(documentation)
