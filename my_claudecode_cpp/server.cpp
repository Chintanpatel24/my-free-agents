#include <iostream>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/version.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/config.hpp>
#include <memory>
#include <string>
#include <thread>
#include "json.hpp"

namespace beast = boost::beast;
namespace http = beast::http;
namespace net = boost::asio;
using tcp = boost::asio::ip::tcp;
using json = nlohmann::json;

void handle_request(http::request<http::string_body>&& req, http::response<http::string_body>& res) {
    if (req.target() == "/health" || req.target() == "/") {
        res.result(http::status::ok);
        res.set(http::field::content_type, "application/json");
        res.body() = "{\"ok\": true, \"engine\": \"cpp\"}";
    } else {
        res.result(http::status::not_found);
        res.body() = "Not Found";
    }
    res.prepare_payload();
}
