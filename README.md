# Sample Task API - Blueprints.md Showcase

This repository demonstrates the use of [Blueprints.md](https://github.com/vtemian/blueprints.md/) for building a complete FastAPI-based task management API.

## What is Blueprints.md?

[Blueprints.md](https://github.com/vtemian/blueprints.md/) is a documentation-driven development approach where markdown files serve as blueprints for generating actual code. It bridges the gap between documentation and implementation, ensuring your docs always reflect your code.

## Project Overview

This sample project implements a task management API with:
- User authentication (JWT-based)
- Task CRUD operations
- User management
- SQLAlchemy models
- FastAPI endpoints

## Structure

```
src/
├── api/
│   ├── tasks.md        # Task endpoints blueprint
│   └── users.md        # User endpoints blueprint
├── core/
│   ├── auth.md         # Authentication logic blueprint
│   └── database.md     # Database configuration blueprint
├── models/
│   ├── task.md         # Task model blueprint
│   └── user.md         # User model blueprint
├── app.md              # Main application blueprint
└── main.md             # Project documentation
```

## How to Use

1. **Explore the blueprints**: Each `.md` file contains the complete implementation details for its respective module
2. **Generate code**: Use [Blueprints.md](https://github.com/vtemian/blueprints.md/) to transform these markdown files into working Python code
3. **Run the application**: Follow the setup instructions in `src/main.md`

## Learn More

- 📚 [Blueprints.md Documentation](https://github.com/vtemian/blueprints.md/)
- 🚀 [Getting Started with Blueprints.md](https://github.com/vtemian/blueprints.md/tree/main?tab=readme-ov-file#%EF%B8%8F-how-it-works---the-agentic-pipeline)
- 💡 [Blueprints.md Examples](https://github.com/vtemian/blueprints.md/tree/main/examples)

## Benefits of Using Blueprints.md

- **Documentation as Code**: Your documentation is your implementation
- **Always Up-to-Date**: No more outdated docs
- **AI-Friendly**: Perfect for AI-assisted development
- **Version Control**: Track changes to both docs and implementation together
- **Readable**: Markdown format is easy to read and write

## License

MIT