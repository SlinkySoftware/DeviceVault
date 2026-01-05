import axios from 'axios'

export default axios.create({ 
  baseURL: 'http://ansible.home.173crs.com:8000' 
})
