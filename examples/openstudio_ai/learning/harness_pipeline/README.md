# Harness Runtime Learning Pipeline

The harness pipeline runs in a distributable agent plugin. It may capture local
experience and propose reusable assets, but it must not directly update trusted
OpenStudio AI assets.

Allowed outputs:

- local recipes;
- session lessons;
- candidate measures;
- candidate eval cases;
- candidate knowledge-base notes.

Promotion into trusted assets is handled by the developer pipeline.

