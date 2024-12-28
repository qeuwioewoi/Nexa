# Nexa - AI-Powered Coding Assistant

Nexa is an intelligent coding assistant designed to revolutionize how developers create, debug, and optimize software. Built with a modern UI and powered by advanced AI models, Nexa provides actionable insights, best practices, and innovative strategies to elevate your coding experience. Whether you're analyzing code, generating new files, or making precise edits, Nexa is your ultimate companion for all things coding.

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Key Features](#key-features)
3. [Installation](#installation)
4. [How to Start](#how-to-start)
5. [FAQs](#faqs)
6. [Contributing](#contributing)
7. [License](#license)
8. [Keywords](#keywords)
9. [Support](#support)

---

## Project Overview

Nexa is an AI-powered coding assistant that helps developers analyze code, generate files, and make precise edits. It leverages advanced AI models to provide structured, actionable responses in JSON format. With a user-friendly interface built using Gradio, Nexa is designed to streamline your coding workflow and enhance productivity.

---

## Key Features

- **Code Analysis & Discussion**:
  - Analyze code with expert-level insights.
  - Explain complex concepts clearly.
  - Suggest optimizations and best practices.
  - Debug issues with precision.

- **File Operations**:
  - Create new files with proper structure.
  - Edit existing files using diff-based editing.
  - Manage multiple files seamlessly.

- **Structured Output**:
  - Receive responses in JSON format for easy integration.
  - Supports structured data for files and edits.

- **Modern UI**:
  - Built with Gradio for an intuitive and interactive experience.
  - Real-time streaming of responses.

- **Customizable**:
  - Easily configure the system prompt and model settings.
  - Supports multiple AI models via Together.ai.

---

## Installation

### Prerequisites
- Python 3.8 or higher
- Git (optional, for cloning the repository)

### Steps to Install
1. **Clone the Repository**:
   ```
   git clone https://github.com/KingLeoJr/Nexa.git
   cd Nexa
   ```

2. **Install Dependencies**:
   - On Windows:
     ```
     install.bat
     ```
   - On macOS/Linux:
     ```
     pip install -r requirements.txt
     ```

3. **Set Up Environment Variables**: 
   Create a `.env` file in the project root and add your API key:
   ```
   API_KEY=your_api_key_here
   ```

---

## How to Start

1. **Run the App**:
   ```
   python app.py
   ```
2. **Access the UI**: Open your browser and navigate to `http://localhost:7860`.
3. **Interact with Nexa**: Type your query in the chat interface. Nexa will analyze your code, generate files, or suggest edits.

---

## FAQs

- **What is Nexa?**
  Nexa is an AI-powered coding assistant that helps developers analyze code, generate files, and make precise edits.

- **Which AI models does Nexa support?**
  Nexa supports all models from OpenAI compatible providers. Update config.coder with baseURL and model name and you are good to go.

- **How do I customize the system prompt?**
  Edit the `system_PROMPT` in the `coder.config` file.

- **What programming languages does Nexa support?**
  Nexa supports all major programming languages, including Python, JavaScript, Java, C++, and more.

---

## Contributing

We welcome contributions! Here’s how you can help:

1. **Fork the Repository**:
   ```
   git clone https://github.com/KingLeoJr/Nexa.git
   ```

2. **Create a Branch**:
   ```
   git checkout -b feature/your-feature-name
   ```

3. **Commit Your Changes**:
   ```
   git commit -m "Add your feature"
   ```

4. **Push to the Branch**:
   ```
   git push origin feature/your-feature-name
   ```

5. **Submit a Pull Request**.

---

## License

This project is licensed under the MIT License. See the LICENSE file for details.

---

## Keywords

AI Coding Assistant, Code Analysis, File Generation, Code Editing, Gradio, Together.ai, LLaMA 2, Starcoder, Mistral 7B, JSON Mode, Function Calling, Open-Source, Developer Tools, Python, JavaScript, Java, C++, Debugging, Optimization, Best Practices.

---

## Support

For support or questions, open an issue on GitHub or contact us at 4leojr@gmail.com.