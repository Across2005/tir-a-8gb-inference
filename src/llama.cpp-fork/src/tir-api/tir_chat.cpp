#include "tir_internal.h"

#include "chat.h"

#include <cstdio>
#include <cstring>
#include <exception>
#include <string>
#include <vector>

namespace {

// JSON string body escaping: quotes, backslash and control chars only.
// Bytes >= 0x80 are passed through, the prompt is already UTF-8.
void json_escape(const std::string & in, std::string & out) {
    out.reserve(out.size() + in.size() + 8);
    for (const char ch : in) {
        const unsigned char c = static_cast<unsigned char>(ch);
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b";  break;
            case '\f': out += "\\f";  break;
            case '\n': out += "\\n";  break;
            case '\r': out += "\\r";  break;
            case '\t': out += "\\t";  break;
            default:
                if (c < 0x20) {
                    char esc[8];
                    std::snprintf(esc, sizeof(esc), "\\u%04x", static_cast<unsigned>(c));
                    out += esc;
                } else {
                    out += ch;
                }
        }
    }
}

void append_json_string(std::string & out, const char * key, const std::string & value) {
    out += '"';
    out += key;
    out += "\":\"";
    json_escape(value, out);
    out += '"';
}

void append_json_int(std::string & out, const char * key, long long value) {
    char num[32];
    std::snprintf(num, sizeof(num), "%lld", value);
    out += '"';
    out += key;
    out += "\":";
    out += num;
}

void append_json_bool(std::string & out, const char * key, bool value) {
    out += '"';
    out += key;
    out += "\":";
    out += value ? "true" : "false";
}

void append_json_string_array(std::string & out, const char * key, const std::vector<std::string> & values) {
    out += '"';
    out += key;
    out += "\":[";
    for (size_t i = 0; i < values.size(); ++i) {
        if (i > 0) {
            out += ',';
        }
        out += '"';
        json_escape(values[i], out);
        out += '"';
    }
    out += ']';
}

// Metadata value as std::string. An absent key yields an empty string.
std::string meta_str(const llama_model * model, const char * key) {
    char probe[8] = { 0 };
    const int32_t n = llama_model_meta_val_str(model, key, probe, sizeof(probe));
    if (n <= 0) {
        return std::string();
    }
    if (static_cast<size_t>(n) < sizeof(probe)) {
        return std::string(probe, static_cast<size_t>(n));
    }
    std::vector<char> buf(static_cast<size_t>(n) + 1, '\0');
    if (llama_model_meta_val_str(model, key, buf.data(), buf.size()) <= 0) {
        return std::string();
    }
    return std::string(buf.data(), static_cast<size_t>(n));
}

// cap == 0: report the required length only.
tir_status copy_out(const std::string & src, char * buf, size_t cap, size_t * out_len) {
    if (out_len == nullptr) {
        tir_detail::set_error("out_len is null");
        return TIR_E_INVALID;
    }
    *out_len = src.size();
    if (cap == 0) {
        return TIR_OK;
    }
    if (buf == nullptr) {
        tir_detail::set_error("out is null but cap is not zero");
        return TIR_E_INVALID;
    }
    if (cap < src.size() + 1) {
        tir_detail::set_error("output buffer is too small");
        return TIR_E_INVALID;
    }
    std::memcpy(buf, src.data(), src.size());
    buf[src.size()] = '\0';
    return TIR_OK;
}

bool engine_ready(const tir_engine * engine) {
    return engine != nullptr && engine->loaded && engine->model != nullptr;
}

} // namespace

extern "C" {

tir_status tir_model_meta(tir_engine * engine, char * buf, size_t cap, size_t * out_len) {
    tir_detail::clear_error();
    try {
        if (!engine_ready(engine)) {
            tir_detail::set_error("engine is null or not loaded");
            return TIR_E_INVALID;
        }
        if (out_len == nullptr) {
            tir_detail::set_error("out_len is null");
            return TIR_E_INVALID;
        }

        const llama_model * model = engine->model;
        const llama_vocab * vocab = llama_model_get_vocab(model);

        std::string tmpl_src;
        bool has_chat_template = false;
        // reasoning markers the host must not hardcode; empty/false when the model has none
        bool supports_thinking = false;
        std::string thinking_start_tag;
        std::vector<std::string> thinking_end_tags;
        std::vector<std::string> additional_stops;
        common_chat_templates_ptr tmpls;
        try {
            tmpls = common_chat_templates_init(model, "");
            if (tmpls) {
                // init falls back to a built-in chatml source when the file carries none,
                // so only an explicit template counts as "the model has one"
                has_chat_template = common_chat_templates_was_explicit(tmpls.get());
                if (has_chat_template) {
                    tmpl_src = common_chat_templates_source(tmpls.get());
                }
            }
        } catch (const std::exception & ex) {
            // a template that does not parse must not hide the rest of the metadata
            tir_detail::set_error((std::string("chat template parse failed: ") + ex.what()).c_str());
            tmpl_src.clear();
            has_chat_template = false;
            tmpls.reset();
        }

        // the markers live in the params, and the meta query has no conversation to feed them
        if (has_chat_template && tmpls) {
            try {
                common_chat_templates_inputs in;
                in.messages.resize(1);
                in.messages[0].role    = "user";
                in.messages[0].content = "x";
                in.use_jinja             = true;
                in.enable_thinking       = true;
                in.add_generation_prompt = true;
                in.add_bos               = false;
                in.add_eos               = false;

                const common_chat_params p = common_chat_templates_apply(tmpls.get(), in);
                supports_thinking  = p.supports_thinking;
                thinking_start_tag = p.thinking_start_tag;
                thinking_end_tags  = p.thinking_end_tags;
                additional_stops   = p.additional_stops;
            } catch (const std::exception & ex) {
                // parser generation can fail on a template that still renders: report no markers
                tir_detail::set_error((std::string("reasoning tag detection failed: ") + ex.what()).c_str());
            }
        }

        const int32_t nextn = llama_model_n_layer_nextn(model);

        std::string json = "{";
        append_json_string(json, "schema", "tir.model-meta/v1");
        json += ',';
        append_json_string(json, "arch", meta_str(model, "general.architecture"));
        json += ',';
        append_json_int(json, "n_layer", llama_model_n_layer(model));
        json += ',';
        append_json_int(json, "n_embd", llama_model_n_embd(model));
        json += ',';
        append_json_int(json, "n_ctx_train", llama_model_n_ctx_train(model));
        json += ',';
        append_json_int(json, "n_vocab", llama_vocab_n_tokens(vocab));
        json += ',';
        append_json_int(json, "nextn", nextn);
        json += ',';
        append_json_bool(json, "mtp", nextn > 0);
        json += ',';
        append_json_int(json, "bos", llama_vocab_bos(vocab));
        json += ',';
        append_json_int(json, "eos", llama_vocab_eos(vocab));
        json += ',';
        append_json_string(json, "chat_template", tmpl_src);
        json += ',';
        append_json_bool(json, "has_chat_template", has_chat_template);
        json += ',';
        append_json_string(json, "thinking_start_tag", thinking_start_tag);
        json += ',';
        append_json_string_array(json, "thinking_end_tags", thinking_end_tags);
        json += ',';
        append_json_string_array(json, "additional_stops", additional_stops);
        json += ',';
        append_json_bool(json, "supports_thinking", supports_thinking);
        json += '}';

        return copy_out(json, buf, cap, out_len);
    } catch (...) {
        tir_detail::set_error("out of memory");
        return TIR_E_OOM;
    }
}

tir_status tir_chat_apply_ex(tir_engine * engine,
                             const tir_chat_message * msgs, size_t n_msgs,
                             const tir_chat_options * opt,
                             char * out, size_t cap, size_t * out_len) {
    tir_detail::clear_error();
    try {
        if (!engine_ready(engine)) {
            tir_detail::set_error("engine is null or not loaded");
            return TIR_E_INVALID;
        }
        if (out_len == nullptr) {
            tir_detail::set_error("out_len is null");
            return TIR_E_INVALID;
        }

        // opt == null: the defaults a plain tir_chat_apply uses
        bool add_generation_prompt = true;
        bool enable_thinking = true;
        if (opt != nullptr) {
            if (!tir_detail::checked_size(opt->struct_size, sizeof(tir_chat_options))) {
                tir_detail::set_error("options struct_size is too small");
                return TIR_E_INVALID;
            }
            if (opt->version != 1) {
                char err[96];
                std::snprintf(err, sizeof(err), "unsupported options version %u", opt->version);
                tir_detail::set_error(err);
                return TIR_E_INVALID;
            }
            if (opt->add_generation_prompt != 0 && opt->add_generation_prompt != 1) {
                char err[96];
                std::snprintf(err, sizeof(err), "add_generation_prompt must be 0 or 1, got %d",
                              static_cast<int>(opt->add_generation_prompt));
                tir_detail::set_error(err);
                return TIR_E_INVALID;
            }
            if (opt->enable_thinking < -1 || opt->enable_thinking > 1) {
                char err[96];
                std::snprintf(err, sizeof(err), "enable_thinking must be -1, 0 or 1, got %d",
                              static_cast<int>(opt->enable_thinking));
                tir_detail::set_error(err);
                return TIR_E_INVALID;
            }
            add_generation_prompt = opt->add_generation_prompt != 0;
            enable_thinking = opt->enable_thinking >= 0 ? opt->enable_thinking != 0 : true;
        }

        if (msgs == nullptr || n_msgs == 0) {
            tir_detail::set_error("msgs is null or n_msgs is zero");
            return TIR_E_INVALID;
        }
        for (size_t i = 0; i < n_msgs; ++i) {
            if (!tir_detail::checked_size(msgs[i].struct_size, sizeof(tir_chat_message))) {
                char err[96];
                std::snprintf(err, sizeof(err), "message %lld struct_size is too small",
                              static_cast<long long>(i));
                tir_detail::set_error(err);
                return TIR_E_INVALID;
            }
            if (msgs[i].version != 1) {
                char err[96];
                std::snprintf(err, sizeof(err), "unsupported message version %u at index %lld",
                              msgs[i].version, static_cast<long long>(i));
                tir_detail::set_error(err);
                return TIR_E_INVALID;
            }
            if (msgs[i].role == nullptr || msgs[i].content == nullptr) {
                char err[96];
                std::snprintf(err, sizeof(err), "message %lld role or content is null",
                              static_cast<long long>(i));
                tir_detail::set_error(err);
                return TIR_E_INVALID;
            }
        }

        std::string prompt;
        try {
            common_chat_templates_ptr tmpls = common_chat_templates_init(engine->model, "");
            if (!tmpls || !common_chat_templates_was_explicit(tmpls.get())) {
                tir_detail::set_error("model has no chat template");
                return TIR_E_MODEL;
            }

            common_chat_templates_inputs in;
            in.add_generation_prompt = add_generation_prompt;
            in.enable_thinking = enable_thinking;
            in.use_jinja = true;
            // the template and the generator own the BOS/EOS decision
            in.add_bos = false;
            in.add_eos = false;
            in.messages.resize(n_msgs);
            for (size_t i = 0; i < n_msgs; ++i) {
                in.messages[i].role = msgs[i].role;
                in.messages[i].content = msgs[i].content;
            }

            prompt = common_chat_templates_apply(tmpls.get(), in).prompt.str();
        } catch (const std::exception & ex) {
            tir_detail::set_error((std::string("chat template apply failed: ") + ex.what()).c_str());
            return TIR_E_MODEL;
        }

        return copy_out(prompt, out, cap, out_len);
    } catch (...) {
        tir_detail::set_error("out of memory");
        return TIR_E_OOM;
    }
}

tir_status tir_chat_apply(tir_engine * engine,
                          const tir_chat_message * msgs, size_t n_msgs,
                          int32_t add_generation_prompt,
                          char * out, size_t cap, size_t * out_len) {
    tir_chat_options opt;
    std::memset(&opt, 0, sizeof(opt));
    opt.struct_size = sizeof(opt);
    opt.version = 1;
    opt.add_generation_prompt = add_generation_prompt != 0 ? 1 : 0;
    opt.enable_thinking = -1;
    return tir_chat_apply_ex(engine, msgs, n_msgs, &opt, out, cap, out_len);
}

} // extern "C"
