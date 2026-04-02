# Contributing

Thank you for your interest in contributing to the AI Advisory Platform.

## How to Contribute

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Test thoroughly: run the pipeline and verify all 6 tabs work
5. Commit: `git commit -m "Add: brief description"`
6. Push: `git push origin feature/your-feature`
7. Open a Pull Request

## Code Standards

- Follow existing file naming conventions
- All database calls go through `db.py`
- Never hardcode credentials — use `.env`
- New data sources should follow the pattern in `fetch_news_api.py`
- New agent nodes should follow the pattern in `agent.py`

## Reporting Issues

Open a GitHub Issue with:
- Description of the problem
- Steps to reproduce
- Expected vs actual behaviour
- Python version and OS

## Adding a New Data Source

1. Create `fetch_yourdata.py` following the pattern in `fetch_news_api.py`
2. Import and call it in `master_pipeline.py`
3. Update `README.md` with the new source

## Adding a New Agent Tool

1. Add a new node function in `agent.py`
2. Register it in `build_agent()` 
3. Add the edge in the graph
4. Update `AdvisorState` if new state fields are needed
