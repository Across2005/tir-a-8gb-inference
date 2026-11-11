#include "stream.h"

#include <algorithm>
#include <utility>

namespace tir::stream {
namespace {

const char * const kToolCallTag = "<tool_call>";

void push(std::vector<Event> & out, Kind kind, const std::string & text) {
    if (!text.empty()) {
        out.push_back(Event{kind, text, ""});
    }
}

} // namespace

size_t ReasoningFilter::find_earliest(const std::string & buf, const std::vector<Pattern> & pats,
                                      size_t & which) {
    size_t best = std::string::npos;
    for (size_t i = 0; i < pats.size(); ++i) {
        const size_t at = buf.find(pats[i].text);
        if (at != std::string::npos && (best == std::string::npos || at < best)) {
            best = at;
            which = i;
        }
    }
    return best;
}

// O(buf * patterns * pattern length); the buffer is short and the lists have a few entries
size_t ReasoningFilter::pending_suffix_len(const std::string & buf, const std::vector<Pattern> & pats) {
    size_t best = 0;
    for (const Pattern & p : pats) {
        // a proper prefix only: a full match was already handled by find_earliest
        const size_t max_len = std::min(buf.size(), p.text.size() - 1);
        for (size_t k = max_len; k > best; --k) {
            if (buf.compare(buf.size() - k, k, p.text, 0, k) == 0) {
                best = k;
                break;
            }
        }
    }
    return best;
}

ReasoningFilter::ReasoningFilter(std::string start_tag, std::vector<std::string> end_tags,
                                 std::vector<std::string> stops, bool starts_in_reasoning)
    : start_tag_(std::move(start_tag)), reasoning_(starts_in_reasoning), stopped_(false),
      trim_newlines_(false) {
    bool has_opener = false;
    for (const std::string & tag : end_tags) {
        if (tag.empty()) {
            continue;
        }
        const bool opener = tag == kToolCallTag;
        has_opener = has_opener || opener;
        reasoning_pats_.push_back(Pattern{tag, opener ? PatKind::ToolCall : PatKind::Terminator});
    }
    // the opener is not always in the model list; it still ends a reasoning segment
    if (!has_opener) {
        reasoning_pats_.push_back(Pattern{kToolCallTag, PatKind::ToolCall});
    }
    for (const std::string & stop : stops) {
        if (stop.empty()) {
            continue;
        }
        // additional_stops are generation-wide, so they apply in both segments
        reasoning_pats_.push_back(Pattern{stop, PatKind::Stop});
        content_pats_.push_back(Pattern{stop, PatKind::Stop});
    }
    // a tool call can open from the content segment too (no-thinking run, or a
    // closer emitted before the opener); a stop with the same text wins the tie
    content_pats_.push_back(Pattern{kToolCallTag, PatKind::ToolCall});
}

std::vector<Event> ReasoningFilter::feed(std::string_view piece, bool final) {
    std::vector<Event> out;
    if (stopped_) {
        return out;
    }
    if (!piece.empty()) {
        // piece.data() may be null for an empty view, so do not append it
        buf_.append(piece.data(), piece.size());
    }

    for (;;) {
        const bool in_reasoning = reasoning_;
        const std::vector<Pattern> & pats = in_reasoning ? reasoning_pats_ : content_pats_;
        const Kind kind = in_reasoning ? Kind::Reasoning : Kind::Content;

        // a reasoning terminator also eats the newline run the template puts after it
        if (!in_reasoning && trim_newlines_) {
            const size_t at = buf_.find_first_not_of('\n');
            if (at == std::string::npos) {
                buf_.clear();
            } else {
                buf_.erase(0, at);
                trim_newlines_ = false;
            }
            if (buf_.empty()) {
                break;
            }
        }

        size_t which = 0;
        const size_t at = find_earliest(buf_, pats, which);
        if (at != std::string::npos) {
            const Pattern hit = pats[which];
            push(out, kind, buf_.substr(0, at));
            buf_.erase(0, at + hit.text.size());
            if (hit.kind == PatKind::Terminator) {
                reasoning_ = false;
                trim_newlines_ = true;
                continue; // the rest of the buffer belongs to the content segment
            }
            const bool tool = hit.kind == PatKind::ToolCall;
            out.push_back(Event{tool ? Kind::ToolCall : Kind::Stop, hit.text, tool ? "tool_call" : "stop"});
            stopped_ = true;
            buf_.clear();
            break;
        }

        if (final) {
            push(out, kind, buf_);
            buf_.clear();
            break;
        }

        // emit the safe part, keep only the suffix that a pattern could complete
        const size_t keep = pending_suffix_len(buf_, pats);
        push(out, kind, buf_.substr(0, buf_.size() - keep));
        buf_.erase(0, buf_.size() - keep);
        break;
    }

    return out;
}

bool ReasoningFilter::stopped() const {
    return stopped_;
}

} // namespace tir::stream
