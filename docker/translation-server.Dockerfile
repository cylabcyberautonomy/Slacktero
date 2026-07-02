# Builds Zotero's translation-server from source, with all its submodules, so
# nothing third-party has to be vendored into this repo. Compose builds this;
# there is no manual pre-clone step.
#
# Pinned to a specific commit for reproducible builds. Bump REF to pull newer
# Zotero translators (and their submodules move with it).
FROM node:lts

ARG REF=d88a8d5384456439962edfef129b14841b09af6d

RUN git clone https://github.com/zotero/translation-server /app \
 && git -C /app checkout "$REF" \
 && git -C /app submodule update --init --recursive --depth 1

WORKDIR /app
RUN npm install

EXPOSE 1969
ENTRYPOINT ["./docker-entrypoint.sh"]
