# Contributing

For general information, see [Ploombers' contributing guidelines.](https://ploomber-contributing.readthedocs.io)

For specific JupySQL contributing guidelines, see the [Developer guide](https://pandry.github.io/jupysql/community/developer-guide.html).

## JupyterLab Extension Development

If you're working on the JupyterLab extension (`jupysql_labextension/`):

1. **Setup**: See [BUILD.md](BUILD.md) for building and running the extension
2. **Development**: See [COMPILE.md](COMPILE.md) for compiling TypeScript changes
3. **Source Code**: Extension code is in `jupysql_labextension/src/`
4. **Watch Mode**: Use `npm run watch` for auto-compilation during development

**Important:** TypeScript files (`.tsx`, `.ts`) must be compiled before changes take effect. The Docker setup handles this automatically.

