#pragma once

#include <string>
#include <string_view>
#include <vector>

namespace tir::stream {

// Done is not produced by the filter; the server layer emits it per stream.
enum class Kind { Reasoning, Content, ToolCall, Stop, Done };

struct Event {
    Kind kind;
    std::string text;    // payload; ToolCall: the matched opener; Stop: the matched stop
    std::string reason;  // Stop: "stop"; ToolCall: "tool_call"; otherwise ""
};

// Splits an incremental token stream into reasoning / content / tool_call / stop
// events. The prompt already opened the reasoning block, so only the terminators
// reported by the model (tir_model_meta thinking_end_tags) are needed here.
//
// Cross-chunk rule: text that may still turn into a tag or a stop is held back.
// A feed emits everything before the longest suffix that is a proper prefix of an
// active pattern, so only that suffix waits for the next piece.
class ReasoningFilter {
public:
    ReasoningFilter(std::string start_tag, std::vector<std::string> end_tags,
                    std::vector<std::string> stops, bool starts_in_reasoning = true);

    // Feed one token piece. final=true flushes the pending text as the current kind.
    std::vector<Event> feed(std::string_view piece, bool final = false);

    bool stopped() const;

private:
    enum class PatKind { Terminator, ToolCall, Stop };
    struct Pattern {
        std::string text;  // never empty
        PatKind kind;
    };

    // earliest match among pats; a tie keeps the lower index
    static size_t find_earliest(const std::string & buf, const std::vector<Pattern> & pats, size_t & which);
    // longest suffix of buf that is a proper prefix of one of pats
    static size_t pending_suffix_len(const std::string & buf, const std::vector<Pattern> & pats);

    std::string start_tag_;  // kept for callers; the prompt already contains it
    std::vector<Pattern> reasoning_pats_;  // end_tags + tool-call opener + stops
    std::vector<Pattern> content_pats_;    // stops + tool-call opener
    std::string buf_;        // text not yet classified
    bool reasoning_;
    bool stopped_;
    bool trim_newlines_;     // content just started after a reasoning terminator
};

} // namespace tir::stream
