FROM ghcr.io/home-assistant/home-assistant:stable

ARG USERNAME=user-name-goes-here
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# Create the user
RUN addgroup --gid $USER_GID $USERNAME \
    && adduser -u $USER_UID -G $USERNAME --disabled-password $USERNAME

RUN chown $USERNAME:$USERNAME /config

# [Optional] Set the default user. Omit if you want to keep the default as root.
USER $USERNAME

RUN mkdir /config/custom_components
