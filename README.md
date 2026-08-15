# Sillo Start

Creates a Sillo application from a starter repository.

```bash
uvx sillo-start create-app myapp
cd myapp
uv sync
uv run sillo db:migrate
uv run sillo serve --reload
```

That is the whole tool. It fetches a real, working application, renames it to
yours, gives it its own secrets, and gets out of the way.

## Why a starter repository, not a generator

A generator renders templates. Templates are checked for *rendering*, which is
not the same as working — a project can produce valid Python, import cleanly,
render every page, and still fail on its first real request. Middleware
registered in the wrong order, an auth backend reading the wrong claim, a
missing static mount: all of them render perfectly.

[`sillohq/starter`](https://github.com/sillohq/starter) is a real application
with its own CI. Every push boots it and exercises every route, on three
Python versions. What you get has been run, not just written.

It also means the starter can be read, forked and improved on its own, and
that `sillo-start` never has to be released to fix a bug in what it produces.

## Install

```bash
# Run it without installing
uvx sillo-start create-app myapp

# Or install it
uv tool install sillo-start
pipx install sillo-start
```

Python 3.11 or newer. The only dependencies are `typer` and `rich`.

## Usage

```bash
sillo-start create-app myapp                       # the default starter
sillo-start create-app sillohq/starter myapp       # named explicitly
sillo-start create-app sillohq/starter@v1.2 myapp  # pinned to a tag
sillo-start create-app acme/our-template myapp     # your own starter
```

Any public GitHub repository works. A full URL is accepted too, so pasting what
is in your address bar does what you expect.

| Option | |
| --- | --- |
| `--ref <branch\|tag>` | Which revision to take. Defaults to `main` |
| `-d`, `--directory <path>` | Where to create it. Defaults to `./<name>` |
| `--install` | Install dependencies straight away |
| `--no-git` | Do not initialise a git repository |
| `--force` | Allow a directory that is not empty |
| `-v`, `--verbose` | Show tracebacks |

Dependencies are **not** installed by default, so creating a project takes a
second rather than a minute. `uv sync` in the new project installs them, and
the command prints the exact next steps for the manager it detected.

## What it does to the project

The starter arrives as a tarball rather than a clone. That needs no `git` on
the machine, brings no history for you to delete before your first commit, and
pins to a tag as easily as to a branch.

Then three things happen:

**It takes your name.** The package name, the application title, the SQLite
path. Rewriting is targeted rather than a blanket find-and-replace, so prose
that happens to say "starter" — a README sentence, a comment — is left as
written.

**It gets its own secrets.** `.env` is created from `.env.example` with a fresh
key for `SECRET_KEY`, `JWT_SECRET` and `APP_KEY`. A secret committed to a
starter is a placeholder by definition; no two projects should ever share a
signing key. An existing `.env` is never touched — it may hold real credentials.

**It becomes a git repository**, unless you pass `--no-git`.

## What it deliberately does not do

Migrations, creating users, running the queue worker, starting the server —
none of that is here.

Those belong to the project, behind its own `sillo` command:

```bash
uv run sillo db:migrate
uv run sillo user:create ada@example.com --admin
uv run sillo queue:work
uv run sillo serve --reload
```

The framework provides the operations as plain functions —
`sillo.record.commands`, `sillo.users.commands`, `sillo.work.commands` — and
the project decides how to expose them. Nothing in a created project depends on
`sillo-start`, so it cannot rot when this tool changes, and you can delete this
tool the moment your project exists.

## Safety

An archive member whose path escapes the destination is refused rather than
sanitised — that is how a malicious archive overwrites files elsewhere on your
machine.

A directory that is not empty is refused unless you pass `--force`, and even
then existing files are left in place.

A project name that is not a usable Python identifier is refused *before*
anything is fetched, since it becomes both a package name and a directory.

## Development

See [docs/contributing.md](docs/contributing.md).

## Licence

BSD-3-Clause.
