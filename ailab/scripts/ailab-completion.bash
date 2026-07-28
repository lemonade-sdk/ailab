_ailab_words_from_command() {
    local kind="$1"
    ailab _complete "$kind" 2>/dev/null
}

_ailab_containers() {
    _ailab_words_from_command containers
}

_ailab_packages() {
    _ailab_words_from_command packages
}

_ailab_compgen_lines() {
    local cur="$1"
    shift
    COMPREPLY=($(compgen -W "$*" -- "$cur"))
}

_ailab_complete() {
    local cur prev words cword

    if declare -F _init_completion >/dev/null 2>&1; then
        _init_completion -n : || return
    else
        words=("${COMP_WORDS[@]}")
        cword=$COMP_CWORD
        cur="${COMP_WORDS[COMP_CWORD]}"
        prev=""
        if [ "$COMP_CWORD" -gt 0 ]; then
            prev="${COMP_WORDS[COMP_CWORD-1]}"
        fi
    fi

    local command="${words[1]:-}"
    local commands="new run stop list ls delete rm install packages pkgs port web dashboard doctor info logs"
    local common_flags="--help --version"

    if [ "$cword" -eq 1 ]; then
        _ailab_compgen_lines "$cur" "$commands $common_flags"
        return
    fi

    case "$command" in
        new)
            case "$prev" in
                --install|-i)
                    _ailab_compgen_lines "$cur" "$(_ailab_packages)"
                    return
                    ;;
            esac
            _ailab_compgen_lines "$cur" "--install -i --port -p --help"
            ;;
        run|shell|stop|delete|rm|info)
            _ailab_compgen_lines "$cur" "$(_ailab_containers)"
            ;;
        logs)
            if [ "$cword" -eq 2 ]; then
                _ailab_compgen_lines "$cur" "$(_ailab_containers)"
            else
                _ailab_compgen_lines "$cur" "--follow -f --lines -n --help"
            fi
            ;;
        install)
            if [ "$cword" -eq 2 ]; then
                _ailab_compgen_lines "$cur" "$(_ailab_containers)"
            elif [ "$cword" -eq 3 ]; then
                _ailab_compgen_lines "$cur" "$(_ailab_packages)"
            fi
            ;;
        packages|pkgs|list|ls|doctor)
            COMPREPLY=()
            ;;
        web)
            _ailab_compgen_lines "$cur" "--host --port -p --reload --help"
            ;;
        dashboard)
            _ailab_compgen_lines "$cur" "--port -p --help"
            ;;
        port)
            if [ "$cword" -eq 2 ]; then
                _ailab_compgen_lines "$cur" "$(_ailab_words_from_command port-actions)"
            elif [ "$cword" -eq 3 ]; then
                _ailab_compgen_lines "$cur" "$(_ailab_containers)"
            else
                case "${words[2]:-}" in
                    add)
                        _ailab_compgen_lines "$cur" "--inbound --help"
                        ;;
                    remove|rm)
                        _ailab_compgen_lines "$cur" "--inbound --help"
                        ;;
                esac
            fi
            ;;
        *)
            COMPREPLY=()
            ;;
    esac
}

complete -F _ailab_complete ailab
