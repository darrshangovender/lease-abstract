# ---- build stage -----------------------------------------------------------
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY lease_abstract ./lease_abstract
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

# ---- runtime stage ---------------------------------------------------------
FROM python:3.12-slim
RUN useradd --create-home --shell /usr/sbin/nologin app
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
WORKDIR /home/app
COPY --chown=app:app demo ./demo
USER app
ENTRYPOINT ["lease-abstract"]
CMD ["check", "demo/leases/01_compliant.txt"]
