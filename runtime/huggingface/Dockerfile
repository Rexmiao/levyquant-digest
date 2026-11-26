FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin app

WORKDIR /home/app/app

COPY requirements-cloud.txt ./requirements-cloud.txt
RUN pip install --no-cache-dir --only-binary=:all: -r requirements-cloud.txt

COPY --chown=1000:1000 levyquant/__init__.py levyquant/daily.py levyquant/editor.py levyquant/feeds.py levyquant/render.py levyquant/smtp_delivery.py levyquant/sources.py levyquant/state_store.py levyquant/space_app.py levyquant/subscriptions.py levyquant/subscription_mail.py ./levyquant/
COPY --chown=1000:1000 config/cloud.json config/official-sources.json config/friend-sources.json ./config/
COPY --chown=1000:1000 tools/editor-output.schema.json ./tools/editor-output.schema.json
COPY --chown=1000:1000 agent.prompt.md ./agent.prompt.md
COPY --chown=1000:1000 runtime/huggingface/static/index.html runtime/huggingface/static/admin.html runtime/huggingface/static/app.js runtime/huggingface/static/app.css ./runtime/huggingface/static/

USER 1000:1000
EXPOSE 7860

CMD ["python", "-m", "levyquant.space_app"]
