<script setup>
import SiteNav from './components/SiteNav.vue'
import HeroSection from './components/HeroSection.vue'
import FeaturesSection from './components/FeaturesSection.vue'
import InstallSection from './components/InstallSection.vue'
import DemoSection from './components/DemoSection.vue'
import FaqSection from './components/FaqSection.vue'
import SiteFooter from './components/SiteFooter.vue'
</script>

<template>
  <SiteNav />
  <main>
    <HeroSection />
    <hr class="cutline" />
    <FeaturesSection />
    <hr class="cutline" />
    <InstallSection />
    <hr class="cutline" />
    <DemoSection />
    <hr class="cutline" />
    <FaqSection />
  </main>
  <SiteFooter />
</template>
