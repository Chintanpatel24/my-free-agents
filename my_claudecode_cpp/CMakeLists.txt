cmake_minimum_required(VERSION 3.10)
project(my_claudecode_cpp)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3 -march=native")

find_package(Boost REQUIRED COMPONENTS system thread)
find_package(OpenSSL REQUIRED)

add_executable(my_claudecode_cpp main.cpp)
target_link_libraries(my_claudecode_cpp Boost::system Boost::thread OpenSSL::SSL OpenSSL::Crypto pthread)
