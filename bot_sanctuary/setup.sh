#!/bin/bash
set -euo pipefail

docker_check()
{
    local target_container="${1:-}"
    if docker inspect "${target_container}" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

stop_docker()
{
    target_container="${1:-}"
    if docker inspect "$target_container" >/dev/null 2>&1; then
        status=$(docker inspect -f '{{.State.Status}}' "$target_container")

        if [[ "$status" == "running" || "$status" == "restarting" ]]; then
            echo "SYSTEM: $target_container stopping..."
            docker stop "$target_container"

            attempts=0
            max_attempts=60
            while (( attempts < max_attempts )); do
                current_state=$(docker inspect -f '{{.State.Status}}' "$target_container")
                [[ "$current_state" == "exited" ]] && break
                sleep 2
                ((attempts++))
            done

            echo "SYSTEM: $target_container stopped."
        fi
    else
        echo "Skip: Docker container $target_container do not exist."
    fi
}

docker_network_check()
{
    if docker network inspect "${CHATBOT_NETWORK_NAME}" >/dev/null 2>&1; then
        echo "Network '${CHATBOT_NETWORK_NAME}' already exists."
    else
        docker network create "${CHATBOT_NETWORK_NAME}"
        echo "Created network '${CHATBOT_NETWORK_NAME}'"
    fi
}

bs_prod_build_docker()
{
    # Docker to build all from <project>/bot_sanctuary
    docker build -f Dockerfile.prod -t "${CHATBOT_BOT_SANCTUARY_PROD_IMAGE_NAME}:${CHATBOT_BOT_SANCTUARY_PROD_VERSION}" .
}

bs_dev_build_docker()
{
    # Docker to build all from <project>/bot_sanctuary
    docker build -f Dockerfile.dev -t "${CHATBOT_BOT_SANCTUARY_DEV_IMAGE_NAME}" .
}

bs_dev_run_docker()
{
    local dev_path="${1:-}"
    bs_dev_remove_docker
    docker_network_check
    if [[ -n "${dev_path}" ]]; then
        echo "Exposed bot_sanctuary_application."
        docker run -d \
            --name "${CHATBOT_BOT_SANCTUARY_DEV_CONTAINER_NAME}" \
            --network "${CHATBOT_NETWORK_NAME}" \
            -e "Q_USER=${CHATBOT_RABBITMQ_USERNAME}" \
            -e "Q_PASSWORD=${CHATBOT_RABBITMQ_PASSWORD}" \
            -e "LLM_TYPE=${CHATBOT_LLM_TYPE}" \
            -e "LLM_OAUTH_TOKEN=${CHATBOT_LLM_OAUTH_TOKEN}" \
            -v "${dev_path}/bot_sanctuary_application:/bot_sanctuary/bot_sanctuary_application" \
            -v "${dev_path}/bot_directory:/home/bot_sanctuary_usr/.claude" \
            "${CHATBOT_BOT_SANCTUARY_DEV_IMAGE_NAME}"
    else
        docker run -d \
            --name "${CHATBOT_BOT_SANCTUARY_DEV_CONTAINER_NAME}" \
            --network "${CHATBOT_NETWORK_NAME}" \
            -e "Q_USER=${CHATBOT_RABBITMQ_USERNAME}" \
            -e "Q_PASSWORD=${CHATBOT_RABBITMQ_PASSWORD}" \
            -e "LLM_TYPE=${CHATBOT_LLM_TYPE}" \
            -e "LLM_OAUTH_TOKEN=${CHATBOT_LLM_OAUTH_TOKEN}" \
            "${CHATBOT_BOT_SANCTUARY_DEV_IMAGE_NAME}"
    fi
}

bs_dev_remove_docker()
{
    stop_docker "${CHATBOT_BOT_SANCTUARY_DEV_CONTAINER_NAME}"
    if docker_check "${CHATBOT_BOT_SANCTUARY_DEV_CONTAINER_NAME}"; then
        docker rm "${CHATBOT_BOT_SANCTUARY_DEV_CONTAINER_NAME}"
    fi
}

bs_dev_access_docker()
{
    docker exec -it "${CHATBOT_BOT_SANCTUARY_DEV_CONTAINER_NAME}" sh
}

bs_dev_show_menu()
{
    local dev_path="${1:-}"
    echo "Select an option:"
    echo "[1] Build Docker Image and Run Container"
    echo "[2] Remove Docker Container"
    echo "[3] Access Docker Container Shell"
    echo "[Q] Quit"
    local setup_select
    read -rp "Select Task: " setup_select

    case "${setup_select}" in
    1)
        bs_dev_build_docker
        bs_dev_run_docker "${dev_path}"
        ;;
    2)
        bs_dev_remove_docker
        ;;
    3)
        bs_dev_access_docker
        ;;
    q|Q)
        exit 0
        ;;
    *)
        echo "Invalid selection.."
        exit 1
        ;;
    esac
}

# DISPLAY MENU ONLY FOR DIRECT EXECUTION.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    config_path="../config.ini"
    if [[ -f "${config_path}" ]]; then
        script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        echo "NOTICE: ${script_dir}"

        source "${config_path}"
        bs_dev_show_menu "${script_dir}"
    else
        echo "NOTICE: ${config_path} not found."
    fi
fi
