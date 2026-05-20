<template>
  <div id="app">
    <Navbar />

    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import Navbar from './components/Navbar.vue' // 방금 만든 네비게이션 임포트
</script>

<style>
/* 전역 스타일 설정 */
body {
  margin: 0;
  font-family: Arial, sans-serif;
  background-color: #f5f5f5;
}
.main-content {
  padding: 2rem;
}
</style>
